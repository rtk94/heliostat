#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Shallow-clone Solaar at pinned tags into .solaar/<tag>/ for the conformance tests.
# Idempotent: a tag that is already checked out at the commit the tag points to is skipped.
#
# Usage: tools/fetch_solaar.sh [tag ...]   (default: the pinned tags below)

set -euo pipefail

REPO_URL="https://github.com/pwr-Solaar/Solaar"
PINNED_TAGS=(1.1.14 1.1.20)

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest_root="$root/.solaar"

if [ "$#" -gt 0 ]; then
    tags=("$@")
else
    tags=("${PINNED_TAGS[@]}")
fi

mkdir -p "$dest_root"

for tag in "${tags[@]}"; do
    dest="$dest_root/$tag"

    # Resolve the tag to a commit on the remote. Annotated tags have a peeled "^{}" entry; prefer it.
    remote_refs="$(git ls-remote --tags "$REPO_URL" "refs/tags/$tag" "refs/tags/$tag^{}")"
    want="$(awk -v r="refs/tags/$tag^{}" '$2 == r { print $1 }' <<<"$remote_refs")"
    if [ -z "$want" ]; then
        want="$(awk -v r="refs/tags/$tag" '$2 == r { print $1 }' <<<"$remote_refs")"
    fi
    if [ -z "$want" ]; then
        echo "error: tag $tag not found in $REPO_URL" >&2
        exit 1
    fi

    if [ -d "$dest/.git" ]; then
        have="$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)"
        if [ "$have" = "$want" ] && git -C "$dest" diff --quiet HEAD 2>/dev/null; then
            echo "$tag: already at ${want:0:12}, skipping"
            continue
        fi
        echo "$tag: have ${have:0:12}, want ${want:0:12}; re-cloning"
        rm -rf "$dest"
    elif [ -e "$dest" ]; then
        echo "$tag: $dest exists but is not a git checkout; re-cloning"
        rm -rf "$dest"
    fi

    echo "$tag: cloning into .solaar/$tag"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$tag" "$REPO_URL" "$dest"
    have="$(git -C "$dest" rev-parse HEAD)"
    if [ "$have" != "$want" ]; then
        echo "error: $tag checked out at $have, expected $want" >&2
        exit 1
    fi
    echo "$tag: checked out at ${have:0:12}"
done
