#!/usr/bin/env bash
# Create the MakeHardware project template repository and push this directory
# into it, then turn on GitHub's "Template repository" switch.
#
# Run this on a machine where `gh auth status` works. It cannot be run from a
# Claude Code cloud session: the session's GitHub token is scoped to a single
# repository and cannot create new ones.
#
#   ./create-template-repo.sh [name] [--public]
#
# Default name: hardware-project-template. Private unless --public is given.
set -euo pipefail

NAME="hardware-project-template"
VISIBILITY="--private"
for arg in "$@"; do
    case "${arg}" in
        --public)  VISIBILITY="--public" ;;
        --private) VISIBILITY="--private" ;;
        -*)        echo "unknown option: ${arg}" >&2; exit 2 ;;
        *)         NAME="${arg}" ;;
    esac
done

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

command -v gh >/dev/null || { echo "gh is not installed: https://cli.github.com" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated. Run: gh auth login" >&2; exit 1; }

OWNER="$(gh api user --jq .login)"
SLUG="${OWNER}/${NAME}"

# Refuse to touch a repo that already exists — this script pushes an initial
# commit, and doing that over someone's work is not recoverable from here.
if gh repo view "${SLUG}" >/dev/null 2>&1; then
    echo "${SLUG} already exists. Delete it or pass a different name." >&2
    exit 1
fi

echo "Creating ${SLUG} (${VISIBILITY#--})"
gh repo create "${SLUG}" "${VISIBILITY}" \
    --description "Template repository for MakeHardware projects"

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

# Everything except this script and the maintainer notes, which belong to
# MakeHardware rather than to the projects made from the template.
# The excludes have to precede the path argument; tar ignores them after it.
tar -C "${HERE}" \
    --exclude=./create-template-repo.sh \
    --exclude=./README-TEMPLATE-NOTES.md \
    -cf - . | tar -C "${STAGE}" -xf -

cd "${STAGE}"
git init -q -b main
git add -A
git commit -q -m "MakeHardware project template

Scaffold the rest with /hw-new-project in the first session."
git remote add origin "https://github.com/${SLUG}"
git push -q -u origin main

echo "Turning on the template switch"
gh api -X PATCH "repos/${SLUG}" -F is_template=true --silent

echo
echo "Done: https://github.com/${SLUG}"
echo "New project:  gh repo create my-widget --template ${SLUG} --private --clone"
echo "Then open a cloud session on it in a MakeHardware environment and run /hw-new-project."
