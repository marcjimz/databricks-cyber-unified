#!/usr/bin/env bash
# Robust frontend dependency install for CI.
#
# ROOT CAUSE (diagnosed from CI logs): the runner's default npm 11.x (bundled
# with Node 24) hangs for ~8 min on BOTH `npm ci` and `npm install`, then dies
# with "Exit handler never called!" -- a known npm 11 bug. It is NOT a lockfile
# problem (installs in ~9s locally on npm 10). The fix is to pin npm to a
# known-good v10 before installing.
#
# This wrapper therefore:
#   * pins npm to 10.x (the actual fix),
#   * bounds each attempt with a hard timeout that also SIGKILLs a wedged npm
#     (plain SIGTERM is ignored while npm is stuck in its broken exit handler),
#   * retries ci -> ci -> install,
#   * VERIFIES the eslint binary exists at the end so the step fails loudly
#     instead of passing green with no node_modules.
set -uo pipefail

cd "$(dirname "$0")/../../app/frontend"

ATTEMPT_TIMEOUT="${NPM_ATTEMPT_TIMEOUT:-240}"   # seconds per attempt
COMMON_FLAGS="--no-audit --no-fund --no-progress"

# Prefer coreutils `timeout` (GitHub Ubuntu runners); fall back to `gtimeout`
# (macOS/Homebrew) or no timeout if neither exists. --kill-after sends SIGKILL
# 30s after SIGTERM so a wedged npm can't outlive the timeout.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

try() {
  echo "::group::npm $* (timeout ${ATTEMPT_TIMEOUT}s)"
  if [ -n "${TIMEOUT_BIN}" ]; then
    "${TIMEOUT_BIN}" --kill-after=30 "${ATTEMPT_TIMEOUT}" npm "$@" ${COMMON_FLAGS}
  else
    npm "$@" ${COMMON_FLAGS}
  fi
  local rc=$?
  echo "::endgroup::"
  return $rc
}

# The actual fix: pin npm to a known-good v10 (the runner default npm 11 hangs).
echo "npm before pin: $(npm --version 2>/dev/null || echo '?')"
npm install -g npm@10 --no-audit --no-fund >/dev/null 2>&1 || echo "warn: could not pin npm@10; continuing"
echo "npm after pin:  $(npm --version 2>/dev/null || echo '?')"

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
