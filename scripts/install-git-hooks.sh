#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

git config core.hooksPath .githooks
printf 'Installed repo git hooks: core.hooksPath=%s\n' "$(git config --get core.hooksPath)"
