#!/bin/bash
# Push a branch to GitLab and open its merge request in the same push, using
# GitLab push options. Works over SSH (ssh-agent) with no glab or API token.
#
# Usage: push-with-mr.sh <worktree> <branch> <expected full sha> <mr-file> [target]
#   mr-file: first line is the MR title; the first paragraph after it becomes
#            the description (push options cannot carry newlines, so it is
#            joined into one line). The commit message carries the full detail.
#
# GitLab acts on push options only when the push updates the ref, so this
# opens an MR for a new or moved branch, not for one already up to date.
set -euo pipefail

wt=$1 branch=$2 sha=$3 mr_file=$4 target=${5:-main}
cd "$wt"

[[ $(git rev-parse "refs/heads/$branch") == "$sha" ]] ||
    { echo "ERROR: $branch is at $(git rev-parse "refs/heads/$branch"), expected $sha" >&2; exit 1; }

title=$(head -1 "$mr_file" | sed 's/^#* *//; s/^Title: *//')
# first non-empty paragraph after the title, as one line
summary=$(tail -n +2 "$mr_file" | awk '/^#/{next} NF{p=1} p&&!NF{exit} p' | tr '\n' ' ' | sed 's/  */ /g; s/ $//')
summary="$summary (Full detail in the commit message.)"

git log --oneline -1 "refs/heads/$branch"
git push origin "refs/heads/$branch:refs/heads/$branch" \
    -o merge_request.create \
    -o merge_request.target="$target" \
    -o merge_request.title="$title" \
    -o merge_request.description="$summary" \
    -o merge_request.remove_source_branch
