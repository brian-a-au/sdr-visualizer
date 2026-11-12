#!/usr/bin/env bash
# Install the Playwright browsers and their system packages for CI.
#
# A normal install takes under a minute. On rare runs the download stalls, and
# without a limit the job then waits for its own 20-minute timeout. This script
# stops each attempt after 5 minutes and tries once more before failing.
#
# Usage: scripts/install_browsers.sh [uv run options...]
# e.g. scripts/install_browsers.sh --locked
set -euo pipefail

attempts=2
limit_seconds=300

for attempt in $(seq 1 "$attempts"); do
  status=0
  timeout --kill-after=30 "$limit_seconds" \
    uv run "$@" playwright install --with-deps chromium webkit || status=$?
  if [[ "$status" -eq 0 ]]; then
    exit 0
  fi
  if [[ "$status" -eq 124 ]]; then
    reason="timed out after ${limit_seconds}s"
  else
    reason="failed with exit status $status"
  fi
  echo "::warning::Browser install attempt $attempt of $attempts $reason"
  if [[ "$attempt" -lt "$attempts" ]]; then
    sleep 15
  fi
done

echo "::error::Browser install did not finish after $attempts attempts"
exit 1
