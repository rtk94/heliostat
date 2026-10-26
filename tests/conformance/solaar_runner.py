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


def main(argv):
    if len(argv) == 3 and argv[0] == "roundtrip":
        command, args = roundtrip, argv[1:]
    elif len(argv) == 2 and argv[0] == "dump-data":
        command, args = dump_data, argv[1:]
    else:
        print(__doc__, file=sys.stderr)
        return 2

    _check_environment()

    errors = _ErrorCounter()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(errors)

    diversion = _import_diversion()
    ok = command(diversion, *args)
    if not ok or errors.count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
