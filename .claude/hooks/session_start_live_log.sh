#!/usr/bin/env bash
# SessionStart: drop a marker the Stop hook compares against, and inject the
# live-logging reminder that used to live in feedback-log-session-files-live.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/_session"
: > "$ROOT/_session/.live_log_marker"

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"LIVE SESSION LOGGING. Append to _session/*.md AS THINGS HAPPEN, not in a batch at the end. A batch written near the end is a reconstruction, not partial credit. hiccups.md: friction, dead ends, wasted effort, facts not self-criticism. deviations.md: where the work departed from the agreed plan. design_changes.md and attributions.md: as they occur. The Stop hook checks hiccups.md once per session."}}
JSON
