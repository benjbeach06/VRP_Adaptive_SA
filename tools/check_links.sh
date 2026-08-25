#!/usr/bin/env bash
# Enforce the doubly-linked reference rule. See planning/doubly-linked-references.md.
#
#     bash tools/check_links.sh              # every in-scope doc
#     bash tools/check_links.sh design/...md # just these
#
# THE RULE, and the direction it flows:
#
#   A file's `## References` is derived from the links in its BODY -- everything before the
#   `## References` heading. That is the only thing an author maintains by hand.
#
#   A file's `## Links to here` is then maintained as a SIDE EFFECT of every other file's
#   References. Nobody edits it speculatively; it fills in as other docs come to cite this one.
#
# So the two checks are:
#
#   1. Does `## References` list exactly the docs the body links to?
#   2. For each of those, does that doc's `## Links to here` name us back?
#
# Links inside fenced code blocks are ignored -- planning/doubly-linked-references.md contains an
# illustrative example that is not a real reference.
#
# Reciprocity is required only between IN-SCOPE docs (see SCOPE below). A link out to an
# experiment folder or a source file is checked for existence and nothing more, because those are
# not documents that maintain back-links.
#
# Reports only. It never writes a back-link: a `Links to here` entry carries a REASON, and an
# invented reason is worse than a missing one because it reads as verified.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

# Docs that participate in the rule.
in_scope() {
    case "$1" in
        design/*.md|planning/*.md|retros/*.md|RESULTS.md|METHODOLOGY.md) return 0 ;;
        *) return 1 ;;
    esac
}

# Everything before the first back-matter heading, with fenced code stripped.
body_of() {
    awk '/^```/ {fenced = !fenced; next} !fenced' "$1" \
        | awk '/^## (References|Links to here|Related|Related experiments)[ \t]*$/ {exit} {print}'
}

# One named section's contents, with fenced code stripped.
section_of() {
    awk -v want="$2" '
        /^```/ {fenced = !fenced; next}
        fenced {next}
        /^## / {inside = ($0 ~ "^## " want "[ \t]*$"); next}
        inside {print}
    ' "$1"
}

# stdin: markdown. $1: directory the links are relative to. stdout: repo-relative paths.
links_in() {
    local dir="$1" link target
    grep -oE '\]\([^)]+\.md[^)]*\)' \
        | sed -e 's/^](//' -e 's/)$//' -e 's/#.*$//' \
        | grep -v '^https\?:' \
        | while read -r link; do
              target="$(realpath -m --relative-to="$ROOT" "$dir/$link" 2>/dev/null)"
              printf '%s\n' "${target//\\//}"
          done \
        | sort -u
}

problems=0
note() { printf '%s\n' "$*"; problems=$((problems + 1)); }

if [ "$#" -gt 0 ]; then
    targets=("$@")
else
    mapfile -t targets < <(find design planning retros -name '*.md' -not -path '*_worktrees*' | sort)
    targets+=(RESULTS.md METHODOLOGY.md)
fi

for f in "${targets[@]}"; do
    [ -f "$f" ] || { note "MISSING FILE   $f"; continue; }
    dir="$(dirname "$f")"

    body_links="$(body_of "$f" | links_in "$dir")"
    listed_refs="$(section_of "$f" References | links_in "$dir")"

    # 0. Every link must resolve, wherever it appears.
    while read -r t; do
        [ -z "$t" ] && continue
        [ -f "$t" ] || note "DANGLING       $f -> $t"
    done < <(cat <(printf '%s\n' "$body_links") \
                 <(section_of "$f" References        | links_in "$dir") \
                 <(section_of "$f" "Links to here"   | links_in "$dir") \
                 <(section_of "$f" Related           | links_in "$dir") \
                 <(section_of "$f" "Related experiments" | links_in "$dir") | sort -u)

    in_scope "$f" || continue

    # 1. References must equal the body's links to DOCUMENTATION. A body link to an experiment
    #    folder, a run log or a source file is NOT a reference -- those go under
    #    "## Related experiments" or stay inline. Existence is still checked, above.
    body_docs="$(printf '%s\n' "$body_links" | while read -r t; do
                     [ -n "$t" ] && in_scope "$t" && printf '%s\n' "$t"
                 done)"

    while read -r t; do
        [ -z "$t" ] && continue
        printf '%s\n' "$listed_refs" | grep -qxF "$t" \
            || note "REF MISSING    $f: body links doc $t, not in ## References"
    done < <(printf '%s\n' "$body_docs")

    while read -r t; do
        [ -z "$t" ] && continue
        in_scope "$t" || { note "REF NOT A DOC  $f: ## References lists $t, not documentation"; continue; }
        printf '%s\n' "$body_docs" | grep -qxF "$t" \
            || note "REF EXTRA      $f: ## References lists $t, body never links it"
    done < <(printf '%s\n' "$listed_refs")

    # 2. Each in-scope reference must name us in its own ## Links to here.
    while read -r t; do
        [ -z "$t" ] && continue
        in_scope "$t" || continue
        [ -f "$t" ] || continue
        back="$(section_of "$t" "Links to here" | links_in "$(dirname "$t")")"
        printf '%s\n' "$back" | grep -qxF "$f" \
            || note "BACKLINK GAP   $t: needs a '## Links to here' entry for $f"
    done < <(printf '%s\n' "$body_docs")
done

if [ "$problems" -eq 0 ]; then
    echo "link check clean: ${#targets[@]} files"
else
    echo
    echo "$problems problem(s)"
fi
exit $(( problems > 0 ))
