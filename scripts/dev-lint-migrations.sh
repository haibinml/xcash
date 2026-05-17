#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

BASE_REF="${MIGRATION_LINTER_BASE:-origin/main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! git rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
  BASE_REF="HEAD"
fi

exec "${SCRIPT_DIR}/dev-manage.sh" lintmigrations --git-commit-id "${BASE_REF}" --no-cache
