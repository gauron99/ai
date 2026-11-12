#!/usr/bin/env bash
# Export one revision of a repo into a new, empty directory. The repo's
# working copy stays as it is.
#
#   export-tree.sh <repo-dir> <rev> <out-dir>
#
# rev: a jj or git revision, or WORKTREE in a git repo: the files on disk,
# tracked and untracked, without ignored ones. Submodules are not exported.
set -euo pipefail
[ $# -eq 3 ] || { sed -n '2,10s/^# \{0,1\}//p' "$0" >&2; exit 2; }
repo=$1 rev=$2 out=$3
if [ -e "$out" ] && [ -n "$(ls -A "$out")" ]; then
  echo "export-tree: $out is not empty" >&2; exit 1
fi
mkdir -p "$out"
if root=$(cd "$repo" && jj --ignore-working-copy root 2>/dev/null); then
  # Without --ignore-working-copy, so jj snapshots first and @ holds unsaved edits.
  commit=$(jj -R "$root" log -r "$rev" --no-graph -T 'commit_id ++ "\n"')
  [ "$(printf '%s\n' "$commit" | wc -l)" -eq 1 ] || { echo "export-tree: $rev is not one revision" >&2; exit 1; }
  git --git-dir="$(jj --ignore-working-copy -R "$root" git root)" archive "$commit" | tar -x -C "$out"
elif root=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null); then
  if [ "$rev" = WORKTREE ]; then
    git -C "$root" ls-files -z --cached --others --exclude-standard |
      while IFS= read -r -d '' f; do [ -e "$root/$f" ] && printf '%s\0' "$f"; done |
      tar -C "$root" --null -T - -cf - | tar -x -C "$out"
  else
    git -C "$root" archive "$rev" | tar -x -C "$out"
  fi
else
  echo "export-tree: $repo is not inside a jj or git repo" >&2; exit 1
fi
echo "exported $rev to $out" >&2
