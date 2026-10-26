# SPDX-License-Identifier: GPL-2.0-or-later
"""Run real Solaar rule load/save code against a rules file.

This script is NOT imported by Heliostat or by pytest. It is run as a subprocess under an
interpreter that has Solaar's dependencies (see README.md), with:

    PYTHONPATH=.solaar/<tag>/lib
    XDG_CONFIG_HOME=<fresh temp dir>

`logitech_receiver.diversion` loads `$XDG_CONFIG_HOME/solaar/rules.yaml` at import time, so the
script refuses to run unless XDG_CONFIG_HOME is set and is not the user's real config dir.

Subcommands:
    roundtrip <in.yaml> <out.yaml>   load with diversion._load_rule_config, save with
                                     diversion._save_config_rule_file
    dump-data <in.yaml>              print JSON of [r.data() for r in <user rules>]
    probe <in.yaml>...               for each file: load, data(), save, reload, data(), save again;
                                     print JSON of what happened at each step (for lint's claims)
    evaluate <in.yaml> <control>     load, then evaluate the rules for a press of <control> as a
                                     REPROG_CONTROLS_V4 notification would; KeyPress actions are
                                     recorded instead of run. Print JSON of the KeyPress keys run

Exit status: 0 on success, 1 if Solaar logged an error (it swallows load and save exceptions and
only logs them), 2 on bad usage or an unsafe environment.
"""

import json
import logging
import os
import pwd
import shutil
import sys


class _ErrorCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1


def _die(message):
    print(f"solaar_runner: {message}", file=sys.stderr)
    sys.exit(2)


def _check_environment():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if not xdg:
        _die("XDG_CONFIG_HOME must be set to a temp dir")
    # The harness points HOME at a temp dir too, so also check the passwd home directory.
    homes = {os.path.expanduser("~"), pwd.getpwuid(os.getuid()).pw_dir}
    for real in {os.path.realpath(os.path.join(home, ".config")) for home in homes}:
        if os.path.realpath(xdg) == real:
            _die(f"refusing to run with XDG_CONFIG_HOME at the real config dir {real}")
    if os.path.exists(os.path.join(xdg, "solaar", "rules.yaml")):
        _die(f"{xdg}/solaar/rules.yaml exists; XDG_CONFIG_HOME must be a fresh dir")


def _import_diversion():
    from logitech_receiver import diversion

    # Make sure we got the pinned checkout from PYTHONPATH, not some installed copy.
    path_entries = [os.path.realpath(p) for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    module_file = os.path.realpath(diversion.__file__)
    if not any(module_file.startswith(p + os.sep) for p in path_entries):
        _die(f"imported diversion from {module_file}, which is not under PYTHONPATH")
    return diversion


def _user_rules(diversion, loaded):
    # _load_rule_config returns Rule([Rule(<user rules>, source=path), built_in_rules]).
    user, built_in = loaded.components
    assert built_in is diversion.built_in_rules
    return user.components


def roundtrip(diversion, in_path, out_path):
    # _save_config_rule_file(name) saves only the rules whose source == name, and _load_rule_config
    # sets source to the path it loaded from. Solaar always loads and saves the same path, so do
    # the same: copy the input to the output path, then load and save that path.
    if os.path.realpath(in_path) != os.path.realpath(out_path):
        shutil.copyfile(in_path, out_path)
    diversion.rules = diversion._load_rule_config(out_path)
    if not diversion._save_config_rule_file(out_path):
        return False
    return True


def dump_data(diversion, in_path):
    loaded = diversion._load_rule_config(in_path)
    json.dump([r.data() for r in _user_rules(diversion, loaded)], sys.stdout, indent=1)
    sys.stdout.write("\n")
    return True


def _load_counting(diversion, errors, path):
    before = errors.count
    loaded = diversion._load_rule_config(path)
    return loaded, errors.count - before


def _data(diversion, loaded):
    try:
        return [r.data() for r in _user_rules(diversion, loaded)], None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _save(diversion, errors, loaded, path):
    """Save as Solaar's editor does. Exceptions from data() escape _save_config_rule_file; others it logs."""
    diversion.rules = loaded
    before = errors.count
    try:
        ok = diversion._save_config_rule_file(path)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return ok and errors.count == before, None


def probe(diversion, errors, *paths):
    results = []
    for in_path in paths:
        out = in_path + ".saved"
        shutil.copyfile(in_path, out)
        original = open(in_path).read()
        loaded, load_errors = _load_counting(diversion, errors, out)
        data, data_error = _data(diversion, loaded)
        saved_ok, save_error = _save(diversion, errors, loaded, out)
        result = {
            "load_errors": load_errors,
            "kept": len(_user_rules(diversion, loaded)),
            "data": data,
            "data_error": data_error,
            "save_ok": saved_ok,
            "save_error": save_error,
            "saved_text": open(out).read(),
            "file_unchanged": open(out).read() == original,
        }
        if saved_ok:
            again = out + ".2"
            shutil.copyfile(out, again)
            reloaded, reload_errors = _load_counting(diversion, errors, again)
            result["reload_errors"] = reload_errors
            result["reload_data"], result["reload_data_error"] = _data(diversion, reloaded)
            result["resave_ok"], result["resave_error"] = _save(diversion, errors, reloaded, again)
        results.append(result)
    json.dump(results, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return True


def evaluate(diversion, in_path, control):
    import types

    ran = []

    def record(self, feature, notification, device, last_result):
        ran.append(list(self.key_names))
        return None

    def components(c):
        yield c
        for child in getattr(c, "components", ()):
            yield from components(child)
        if isinstance(c, diversion.Not):
            yield from components(c.component)

    loaded = diversion._load_rule_config(in_path)
    for c in components(loaded):
        # Only KeyPress is safe to "run" (it is recorded, not sent); the others would act on the system.
        if isinstance(c, diversion.Action) and not isinstance(c, diversion.KeyPress):
            _die(f"evaluate only allows KeyPress actions, found {c}")
    diversion.KeyPress.evaluate = record
    diversion.rules = loaded
    diversion.key_down, diversion.key_up = diversion.CONTROL[control], None
    notification = types.SimpleNamespace(address=0x00, data=bytes(16))
    device = types.SimpleNamespace(unitId="AAAA0002", serial="AAAA0002", codename="M650", name="Mouse")
    diversion.evaluate_rules(diversion.SupportedFeature.REPROG_CONTROLS_V4, notification, device)
    json.dump(ran, sys.stdout)
    sys.stdout.write("\n")
    return True


def main(argv):
    if len(argv) == 3 and argv[0] == "roundtrip":
        command, args = roundtrip, argv[1:]
    elif len(argv) == 2 and argv[0] == "dump-data":
        command, args = dump_data, argv[1:]
    elif len(argv) >= 2 and argv[0] == "probe":
        command, args = probe, argv[1:]
    elif len(argv) == 3 and argv[0] == "evaluate":
        command, args = evaluate, argv[1:]
    else:
        print(__doc__, file=sys.stderr)
        return 2

    _check_environment()

    errors = _ErrorCounter()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(errors)

    diversion = _import_diversion()
    if command is probe:
        return 0 if probe(diversion, errors, *args) else 1  # errors are reported per file
    ok = command(diversion, *args)
    if not ok or errors.count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
