#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
UPGRADE_REF="${1:-${UPGRADE_REF:-main}}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-false}"
QUIESCE_BEFORE_REHEARSAL="${QUIESCE_BEFORE_REHEARSAL:-false}"

COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
REHEARSAL_COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile migration-rehearsal)
TMP_DIR=""

log() {
  printf '[upgrade] %s\n' "$*"
}

die() {
  printf '[upgrade] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local exit_code=$?

  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi

  "${REHEARSAL_COMPOSE[@]}" rm -sf migration-rehearsal-db migration-rehearsal-signer-db >/dev/null 2>&1 || true

  exit "${exit_code}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

ensure_git_clean() {
  if [[ "${ALLOW_DIRTY_UPGRADE:-false}" == "true" ]]; then
    return
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    die "git worktree is dirty; commit or stash changes before production upgrade"
  fi
}

pull_code() {
  if [[ "${SKIP_GIT_PULL}" == "true" ]]; then
    log "skip git pull; using current working tree"
    return
  fi

  ensure_git_clean
  log "fetch and fast-forward ${UPGRADE_REF}"
  git fetch --prune
  git checkout "${UPGRADE_REF}"
  git pull --ff-only
  ensure_git_clean
}

wait_for_postgres() {
  local service="$1"
  local compose=("${COMPOSE[@]}")

  if [[ "${service}" == migration-rehearsal-* ]]; then
    compose=("${REHEARSAL_COMPOSE[@]}")
  fi

  log "wait for ${service}"
  "${compose[@]}" exec -T "${service}" sh -c \
    'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do sleep 1; done'
}

dump_database() {
  local service="$1"
  local output="$2"

  log "dump ${service}"
  "${COMPOSE[@]}" exec -T "${service}" sh -c \
    'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >"${output}"
}

restore_database() {
  local service="$1"
  local input="$2"
  local compose=("${COMPOSE[@]}")

  if [[ "${service}" == migration-rehearsal-* ]]; then
    compose=("${REHEARSAL_COMPOSE[@]}")
  fi

  log "restore dump into ${service}"
  "${compose[@]}" exec -T "${service}" sh -c \
    'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <"${input}"
}

run_main_manage() {
  local postgres_host="$1"
  shift

  "${COMPOSE[@]}" run --rm --no-deps \
    -e XCASH_IGNORE_DATABASE_URL=true \
    -e POSTGRES_HOST="${postgres_host}" \
    -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    django python manage.py "$@"
}

run_signer_manage() {
  local postgres_host="$1"
  shift

  "${COMPOSE[@]}" run --rm --no-deps \
    -e SIGNER_POSTGRES_HOST="${postgres_host}" \
    -e SIGNER_POSTGRES_PASSWORD="${SIGNER_POSTGRES_PASSWORD}" \
    signer bash -lc 'cd /app/signer && python manage.py "$@"' signer-manage "$@"
}

compare_plans() {
  local rehearsal_plan="$1"
  local production_plan="$2"
  local label="$3"

  if ! diff -u "${rehearsal_plan}" "${production_plan}"; then
    die "${label} migrate --plan differs between rehearsal and production"
  fi
}

trap cleanup EXIT

require_command docker
require_command git

[[ -f "${ENV_FILE}" ]] || die "env file not found: ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "compose file not found: ${COMPOSE_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

[[ -n "${POSTGRES_PASSWORD:-}" ]] || die "POSTGRES_PASSWORD is required"
[[ -n "${SIGNER_POSTGRES_PASSWORD:-}" ]] || die "SIGNER_POSTGRES_PASSWORD is required"

TMP_DIR="$(mktemp -d)"
MAIN_DUMP="${TMP_DIR}/xcash-main.dump"
SIGNER_DUMP="${TMP_DIR}/xcash-signer.dump"
MAIN_REHEARSAL_PLAN="${TMP_DIR}/main-rehearsal.plan"
MAIN_PRODUCTION_PLAN="${TMP_DIR}/main-production.plan"
SIGNER_REHEARSAL_PLAN="${TMP_DIR}/signer-rehearsal.plan"
SIGNER_PRODUCTION_PLAN="${TMP_DIR}/signer-production.plan"

pull_code

log "build production images"
"${COMPOSE[@]}" build

log "start database and cache dependencies"
"${COMPOSE[@]}" up -d django-db signer-db redis
wait_for_postgres django-db
wait_for_postgres signer-db

if [[ "${QUIESCE_BEFORE_REHEARSAL}" == "true" ]]; then
  log "stop app services before rehearsal"
  "${COMPOSE[@]}" stop django worker beat signer || true
fi

dump_database django-db "${MAIN_DUMP}"
dump_database signer-db "${SIGNER_DUMP}"

log "reset rehearsal databases"
"${REHEARSAL_COMPOSE[@]}" rm -sf migration-rehearsal-db migration-rehearsal-signer-db >/dev/null 2>&1 || true
"${REHEARSAL_COMPOSE[@]}" up -d migration-rehearsal-db migration-rehearsal-signer-db
wait_for_postgres migration-rehearsal-db
wait_for_postgres migration-rehearsal-signer-db

restore_database migration-rehearsal-db "${MAIN_DUMP}"
restore_database migration-rehearsal-signer-db "${SIGNER_DUMP}"

log "run main database migration rehearsal"
run_main_manage migration-rehearsal-db migrate --plan | tee "${MAIN_REHEARSAL_PLAN}"
run_main_manage migration-rehearsal-db migrate --noinput
run_main_manage migration-rehearsal-db check --deploy

log "run signer database migration rehearsal"
run_signer_manage migration-rehearsal-signer-db migrate --plan | tee "${SIGNER_REHEARSAL_PLAN}"
run_signer_manage migration-rehearsal-signer-db migrate --noinput

log "stop app services before production migration"
"${COMPOSE[@]}" stop django worker beat signer || true

log "verify production migration plans"
run_main_manage django-db migrate --plan | tee "${MAIN_PRODUCTION_PLAN}"
compare_plans "${MAIN_REHEARSAL_PLAN}" "${MAIN_PRODUCTION_PLAN}" "main database"
run_signer_manage signer-db migrate --plan | tee "${SIGNER_PRODUCTION_PLAN}"
compare_plans "${SIGNER_REHEARSAL_PLAN}" "${SIGNER_PRODUCTION_PLAN}" "signer database"

log "apply production migrations"
run_main_manage django-db migrate --noinput
run_signer_manage signer-db migrate --noinput

log "run production post-migration setup"
run_main_manage django-db collectstatic --noinput
run_main_manage django-db ensure_default_superuser

log "start application services"
"${COMPOSE[@]}" up -d --remove-orphans

log "upgrade completed"
