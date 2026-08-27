#!/bin/bash
# Runs link_scan.py over a list of files, archiving each file's log output
# separately so a later scan in the same batch never clobbers an earlier
# file's still-unprocessed log.
#
# Usage: bash tools/batch_link_scan.sh <file1> <file2> ...
#
# Output: _session/link_logs/<NNN>__<sanitized-path>.md for every file that
# produced a non-empty log. Empty logs are not archived. The shared
# _session/link_script_output.md is deleted after each run regardless, so it
# never carries stale content into the next invocation of the skill.
#
# Process the archived logs in order (ls _session/link_logs/ | sort), one at
# a time, exactly as the link_doc_file skill processes the shared log --
# grep context, write explanations, apply via link_annotate.py -- then
# delete that archived log file when done with it.

set -euo pipefail

mkdir -p _session/link_logs
rm -f _session/link_logs/*.md

n=0
for file in "$@"; do
  n=$((n + 1))
  idx=$(printf "%03d" "$n")
  safe=$(echo "$file" | tr '/' '_')

  rm -f _session/link_script_output.md
  python tools/link_scan.py "$file"

  if [ -s _session/link_script_output.md ]; then
    cp _session/link_script_output.md "_session/link_logs/${idx}__${safe}.md"
    echo "CHANGES: $file -> _session/link_logs/${idx}__${safe}.md"
  else
    echo "no changes: $file"
  fi
  rm -f _session/link_script_output.md
done
