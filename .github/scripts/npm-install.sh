#!/usr/bin/env bash
# Robust frontend dependency install for CI.
#
# The GitHub runner's npm has been hanging on `npm ci` for ~8 min and then dying
# with "Exit handler never called!" (an npm-internal bug), even though the
# lockfile installs cleanly in seconds locally. This wrapper:
#   * bounds each attempt with a hard timeout (fail fast, don't hang the job),
#   * retries, and falls back from `npm ci` to `npm install` (a different npm
#     code path that commonly sidesteps the hang),
#   * VERIFIES the eslint binary exists at the end so the step fails loudly
#     instead of passing green with no node_modules.
set -uo pipefail

cd "$(dirname "$0")/../../app/frontend"

ATTEMPT_TIMEOUT="${NPM_ATTEMPT_TIMEOUT:-240}"   # seconds per attempt
COMMON_FLAGS="--no-audit --no-fund --no-progress"

# Prefer coreutils `timeout` (present on GitHub Ubuntu runners); fall back to
# `gtimeout` (macOS/Homebrew) or no timeout at all if neither exists.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

try() {
  echo "::group::npm $* (timeout ${ATTEMPT_TIMEOUT}s)"
  if [ -n "${TIMEOUT_BIN}" ]; then
    "${TIMEOUT_BIN}" "${ATTEMPT_TIMEOUT}" npm "$@" ${COMMON_FLAGS}
  else
    npm "$@" ${COMMON_FLAGS}
  fi
  local rc=$?
  echo "::endgroup::"
  return $rc
}

npm cache verify >/dev/null 2>&1 || true

# 1) npm ci (twice), 2) fall back to npm install.
for attempt in ci-1 ci-2 install; do
  case "$attempt" in
    ci-*)    try ci && break ;;
    install) echo "npm ci failed; falling back to npm install"; rm -rf node_modules; try install && break ;;
  esac
  echo "install attempt '$attempt' failed; cleaning + retrying"
  rm -rf node_modules ~/.npm/_cacache 2>/dev/null || true
  sleep 5
done

# Fail loudly if the eslint binary is still missing (prevents a false-green step).
if [ ! -x node_modules/.bin/eslint ]; then
  echo "::error::frontend dependencies did not install (node_modules/.bin/eslint missing)"
  exit 1
fi
echo "frontend dependencies installed; eslint present."
