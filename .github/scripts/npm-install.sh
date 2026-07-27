#!/usr/bin/env bash
# Robust frontend dependency install for CI.
#
# ROOT CAUSE (diagnosed from CI logs): package-lock.json resolves every package
# from `npm-proxy.dev.databricks.com` -- an INTERNAL Databricks registry baked in
# when the lockfile was generated on the corp network. GitHub runners can't reach
# that host, so npm hangs on connect until killed. (It "works locally" only
# because the dev's ~/.npmrc points at that proxy + they're on the VPN.)
#
# Fix: force the PUBLIC npm registry for the CI install, overriding the internal
# proxy in the lockfile. We also:
#   * bound each attempt with a hard timeout that SIGKILLs a wedged npm,
#   * retry ci -> ci -> install,
#   * VERIFY the eslint binary exists at the end so the step fails loudly instead
#     of passing green with no node_modules.
set -uo pipefail

cd "$(dirname "$0")/../../app/frontend"

ATTEMPT_TIMEOUT="${NPM_ATTEMPT_TIMEOUT:-180}"   # seconds per attempt
REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org/}"
# Force the public registry (override any internal proxy in the lockfile/env),
# be resilient to slow mirrors, and keep output quiet-but-diagnosable.
COMMON_FLAGS="--registry=${REGISTRY} --no-audit --no-fund --no-progress --fetch-timeout=60000 --fetch-retries=3"

TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

try() {
  echo "::group::npm $* (registry=${REGISTRY}, timeout ${ATTEMPT_TIMEOUT}s)"
  if [ -n "${TIMEOUT_BIN}" ]; then
    "${TIMEOUT_BIN}" --kill-after=20 "${ATTEMPT_TIMEOUT}" npm "$@" ${COMMON_FLAGS}
  else
    npm "$@" ${COMMON_FLAGS}
  fi
  local rc=$?
  echo "::endgroup::"
  return $rc
}

# Belt and suspenders: also pin the registry via env for any child npm process.
export npm_config_registry="${REGISTRY}"

npm cache verify >/dev/null 2>&1 || true

# 1) npm ci (twice), 2) fall back to npm install (regenerates against the public
#    registry if the lockfile's internal-proxy URLs still trip `npm ci`).
for attempt in ci-1 ci-2 install; do
  case "$attempt" in
    ci-*)    try ci && break ;;
    install) echo "npm ci failed; falling back to npm install"; rm -rf node_modules; try install && break ;;
  esac
  echo "install attempt '$attempt' failed; cleaning + retrying"
  rm -rf node_modules 2>/dev/null || true
  sleep 3
done

if [ ! -x node_modules/.bin/eslint ]; then
  echo "::error::frontend dependencies did not install (node_modules/.bin/eslint missing)"
  exit 1
fi
echo "frontend dependencies installed; eslint present."
