#!/usr/bin/env bash
# Commit what changed in a public data repo checkout and push it, merging with
# whatever the other writer (collector or pipeline) pushed meanwhile.
#   bash scripts/push_repo.sh <checkout> <commit message>
# Prints "pushed" when something was pushed.
set -euo pipefail
dir="$1"; msg="$2"
tools="$(cd "$(dirname "$0")" && pwd)"
cd "$dir"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git config merge.videos.driver "python3 $tools/merge_videos.py %O %A %B"
git config merge.keep.driver true   # generated files: keep either, rebuilt below
printf 'data/videos.json merge=videos\nREADME*.md merge=keep\ndata/readme.json merge=keep\n' > .git/info/attributes

git add -A data README*.md $( [ -d prompts ] && echo prompts )
git diff --cached --quiet && exit 0
git commit -q -m "$msg"
for attempt in 1 2 3 4 5; do
  git pull -q --rebase
  out=$(python3 scripts/validate.py 2>&1) || { echo "$out"; exit 1; }
  python3 scripts/build_readme.py >/dev/null
  if ! git diff --quiet; then
    git add -A README*.md
    git commit -q --amend --no-edit
  fi
  if git push -q; then
    echo pushed
    exit 0
  fi
  sleep $((attempt * 5))
done
echo "::error::$(basename "$dir"): push failed after 5 attempts"
exit 1
