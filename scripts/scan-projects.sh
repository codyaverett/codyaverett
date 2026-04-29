#!/usr/bin/env bash
# scan-projects.sh — survey local git repos under PROJECTS_ROOT and emit a
# ranked report intended for an LLM agent to use when curating the
# "Featured Projects" section of the profile README.
#
# Read-only: writes nothing outside scripts/projects-report.md (and stdout).
#
# Usage:
#   bash scripts/scan-projects.sh                # default: top 10
#   bash scripts/scan-projects.sh --top 20
#   bash scripts/scan-projects.sh --json         # JSON only, no markdown file
#   bash scripts/scan-projects.sh --root /path   # override PROJECTS_ROOT
#
# Exit codes: 0 ok, 1 usage error, 2 root not found.

set -euo pipefail

PROJECTS_ROOT="${PROJECTS_ROOT:-/Users/caavere/Projects}"
USER_EMAIL="${USER_EMAIL:-codyaverett@gmail.com}"
TOP=10
JSON_ONLY=0
SKIP_DIRS=("codyaverett" "memento" "archive" "_helping")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --top) TOP="$2"; shift 2 ;;
    --json) JSON_ONLY=1; shift ;;
    --root) PROJECTS_ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -d "$PROJECTS_ROOT" ]] || { echo "root not found: $PROJECTS_ROOT" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="$SCRIPT_DIR/projects-report.md"

is_skipped() {
  local name="$1"
  for s in "${SKIP_DIRS[@]}"; do [[ "$name" == "$s" ]] && return 0; done
  return 1
}

top_language() {
  # naive: count tracked files by extension; ignore vendored/build dirs
  local dir="$1"
  git -C "$dir" ls-files 2>/dev/null \
    | grep -Ev '(^|/)(node_modules|dist|build|\.next|target|vendor|\.venv)/' \
    | awk -F. 'NF>1 { ext=$NF; if (length(ext) <= 6) c[tolower(ext)]++ } END { for (k in c) print c[k], k }' \
    | sort -rn | head -1 | awk '{print $2}'
}

readme_first_line() {
  local dir="$1"
  for f in README.md README.MD readme.md README.markdown README; do
    [[ -f "$dir/$f" ]] || continue
    # first non-empty, non-heading-only, non-image-only line, stripped of markdown
    awk '
      /^[[:space:]]*$/ { next }
      /^#+[[:space:]]/ { next }
      /^!\[/ { next }
      /^<[^>]+>[[:space:]]*$/ { next }
      { gsub(/^[[:space:]]+|[[:space:]]+$/,""); print; exit }
    ' "$dir/$f"
    return
  done
}

stack_hints() {
  local dir="$1" hints=()
  [[ -f "$dir/package.json" ]] && hints+=("node")
  [[ -f "$dir/deno.json" || -f "$dir/deno.jsonc" ]] && hints+=("deno")
  [[ -f "$dir/Cargo.toml" ]] && hints+=("rust")
  [[ -f "$dir/go.mod" ]] && hints+=("go")
  [[ -f "$dir/pyproject.toml" || -f "$dir/requirements.txt" ]] && hints+=("python")
  [[ -f "$dir/pom.xml" || -f "$dir/build.gradle" || -f "$dir/build.gradle.kts" ]] && hints+=("jvm")
  [[ -f "$dir/Dockerfile" || -f "$dir/compose.yml" || -f "$dir/docker-compose.yml" ]] && hints+=("docker")
  (IFS=,; echo "${hints[*]:-}")
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n")))' 2>/dev/null \
    || awk 'BEGIN{ORS=""} {gsub(/\\/,"\\\\"); gsub(/"/,"\\\""); gsub(/\t/,"\\t"); gsub(/\r/,""); printf "%s%s", (NR>1?"\\n":""), $0} END{print ""}'
}

# Collect into arrays
declare -a ROWS_JSON=()
declare -a ROWS_TSV=()  # score \t name \t recent90 \t last_date \t lang \t stack \t remote \t desc

since_iso="$(date -v-90d +%Y-%m-%d 2>/dev/null || date -d '90 days ago' +%Y-%m-%d)"

for dir in "$PROJECTS_ROOT"/*/; do
  name="$(basename "$dir")"
  is_skipped "$name" && continue
  [[ -d "$dir/.git" ]] || continue

  remote="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
  last_date="$(git -C "$dir" log -1 --format=%cs --author="$USER_EMAIL" 2>/dev/null || true)"
  if [[ -z "$last_date" ]]; then
    last_date="$(git -C "$dir" log -1 --format=%cs 2>/dev/null || true)"
    authored_by_user=0
  else
    authored_by_user=1
  fi
  [[ -z "$last_date" ]] && continue

  recent90="$(git -C "$dir" log --since="$since_iso" --author="$USER_EMAIL" --oneline 2>/dev/null | wc -l | tr -d ' ')"
  total_commits="$(git -C "$dir" rev-list --count HEAD 2>/dev/null || echo 0)"
  lang="$(top_language "$dir" || true)"
  stack="$(stack_hints "$dir")"
  desc="$(readme_first_line "$dir" || true)"

  # score: weight recent activity heavily, light bonus for user-authored and remote presence
  days_ago=$(( ( $(date +%s) - $(date -j -f %Y-%m-%d "$last_date" +%s 2>/dev/null || date -d "$last_date" +%s) ) / 86400 ))
  recency_score=$(( days_ago < 1 ? 100 : (days_ago < 7 ? 80 : (days_ago < 30 ? 60 : (days_ago < 90 ? 40 : (days_ago < 365 ? 15 : 2)))) ))
  score=$(( recency_score + recent90 * 2 + (authored_by_user * 5) ))
  [[ -n "$remote" ]] && score=$(( score + 3 ))

  ROWS_TSV+=("$(printf '%d\t%s\t%d\t%s\t%s\t%s\t%s\t%s\t%d\t%d' \
    "$score" "$name" "$recent90" "$last_date" "${lang:-}" "${stack:-}" "${remote:-}" "${desc:-}" "$total_commits" "$days_ago")")

  desc_j="$(printf '%s' "${desc:-}" | json_escape)"
  remote_j="$(printf '%s' "${remote:-}" | json_escape)"
  lang_j="$(printf '%s' "${lang:-}" | json_escape)"
  stack_j="$(printf '%s' "${stack:-}" | json_escape)"
  ROWS_JSON+=("$(cat <<EOF
{"name":"$name","path":"${dir%/}","remote":$remote_j,"last_commit":"$last_date","days_since":$days_ago,"recent_90d_commits":$recent90,"total_commits":$total_commits,"top_language":$lang_j,"stack":$stack_j,"authored_by_user":$([[ $authored_by_user -eq 1 ]] && echo true || echo false),"score":$score,"description_seed":$desc_j}
EOF
  )")
done

# Print JSON to stdout (newline-delimited JSON, easy to parse)
printf '%s\n' "${ROWS_JSON[@]}" | sort -t'"' -k20 -rn 2>/dev/null || printf '%s\n' "${ROWS_JSON[@]}"

[[ "$JSON_ONLY" -eq 1 ]] && exit 0

# Build ranked markdown report
{
  echo "# Local Projects Report"
  echo
  echo "_Generated: $(date '+%Y-%m-%d %H:%M %Z')  •  root: \`$PROJECTS_ROOT\`  •  showing top $TOP by activity score._"
  echo
  echo "Score weights recency, commits in last 90d, whether you authored, and whether a remote is set."
  echo "Use this list to pick 3-5 projects for the **Featured Projects** section in README.md."
  echo
  echo "| # | Project | Last commit | 90d commits | Lang | Stack | Remote | Seed description |"
  echo "|--:|---|---|--:|---|---|---|---|"
  printf '%s\n' "${ROWS_TSV[@]}" | sort -rn | head -n "$TOP" | awk -F'\t' '
    BEGIN{i=0}
    {
      i++
      remote=$7; if (remote=="") remote="—"
      else { sub(/^git@github\.com:/,"https://github.com/",remote); sub(/\.git$/,"",remote); remote="["$2"]("remote")" }
      desc=$8; gsub(/\|/,"\\|",desc); if (length(desc) > 120) desc=substr(desc,1,117)"…"
      printf "| %d | **%s** | %s | %s | %s | %s | %s | %s |\n", i, $2, $4, $3, ($5==""?"—":$5), ($6==""?"—":$6), remote, (desc==""?"—":desc)
    }'
  echo
  echo "## Suggested next step for an agent"
  echo
  echo "1. Pick 3-5 rows from the top of this table that best represent recent, public, interesting work."
  echo "2. Draft a one-line description for each (use the seed, but rewrite for clarity)."
  echo "3. Update the **Featured Projects** section of \`README.md\` with the picks."
} > "$REPORT"

echo "wrote: $REPORT" >&2
