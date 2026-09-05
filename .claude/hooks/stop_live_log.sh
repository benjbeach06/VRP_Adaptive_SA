#!/usr/bin/env bash
# Stop: if nothing reached _session/hiccups.md this session, block ONCE and ask
# for it. Single-shot -- the marker is removed after firing, so a session is
# never interrupted twice and a quiet session is never blocked at all.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARKER="$ROOT/_session/.live_log_marker"
HICCUPS="$ROOT/_session/hiccups.md"

INPUT="$(cat)"
# Never re-block a turn that is already continuing because of this hook.
if printf '%s' "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then exit 0; fi
[ -f "$MARKER" ] || exit 0
# hiccups.md already touched since the session began -- nothing to ask for.
if [ -f "$HICCUPS" ] && [ "$HICCUPS" -nt "$MARKER" ]; then exit 0; fi

rm -f "$MARKER"
cat <<'JSON'
{"decision":"block","reason":"Nothing was appended to _session/hiccups.md this session. Before finishing: append any friction, dead end, wrong turn or wasted effort from this session as plain facts, and log anything that belongs in deviations.md, design_changes.md or attributions.md. If genuinely nothing happened worth recording, say so in one line and finish -- this check fires only once per session."}
JSON
