#!/usr/bin/env bash
# verified-commit.sh — land changed files as a single commit via the GraphQL
# createCommitOnBranch API.
#
# Usage: verified-commit.sh "headline" <path-or-glob>...
#   e.g. verified-commit.sh "chore(metrics): refresh profile dashboards" '*.svg'
#
# Why the API instead of git commit: commits created this way are signed by
# GitHub itself, so they show the Verified badge with zero key management,
# and the workflow needs no committer identity at all.
#
# The commit message carries structured trailers (Workflow, Run, Files,
# Inputs-SHA256 of the workflow definition), making git log a queryable
# ledger of what the automation did and exactly which workflow did it:
#   git log --format='%h %(trailers:key=Workflow,valueonly) %(trailers:key=Files,valueonly)'
#
# Expects: gh authenticated (GH_TOKEN); GITHUB_REPOSITORY, GITHUB_RUN_ID and
# GITHUB_WORKFLOW_REF in env (set by Actions; falls back for local dry runs).
#
# Exit codes: 0 ok (including nothing-to-commit), 1 usage/API error.

set -euo pipefail

[[ $# -ge 2 ]] || { echo "usage: $0 \"headline\" <path>..." >&2; exit 1; }
headline="$1"
shift

REPO="${GITHUB_REPOSITORY:-codyaverett/codyaverett}"
RUN_ID="${GITHUB_RUN_ID:-local}"
BRANCH="${BRANCH:-main}"

# owner/repo/.github/workflows/x.yml@refs/heads/main -> .github/workflows/x.yml
workflow_ref="${GITHUB_WORKFLOW_REF:-$REPO/.github/workflows/unknown.yml@local}"
workflow_path="${workflow_ref#"$REPO"/}"
workflow_path="${workflow_path%@*}"

mapfile -t changed < <(git diff --name-only -- "$@")
if [[ ${#changed[@]} -eq 0 ]]; then
  echo "no changes to commit"
  exit 0
fi
echo "changed: ${changed[*]}"

head_oid="$(git rev-parse HEAD)"
inputs_sha="$( [[ -f "$workflow_path" ]] && sha256sum "$workflow_path" | cut -d' ' -f1 || echo "unknown" )"

message_body="$(printf 'Workflow: %s\nRun: https://github.com/%s/actions/runs/%s\nFiles: %s\nInputs-SHA256: %s' \
  "$(basename "$workflow_path")" "$REPO" "$RUN_ID" "${changed[*]}" "$inputs_sha")"

additions="$(for f in "${changed[@]}"; do
  jq -n --arg path "$f" --arg contents "$(base64 <"$f" | tr -d '\n')" \
    '{path: $path, contents: $contents}'
done | jq -s .)"

query='mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}'

jq -n \
  --arg query "$query" \
  --arg repo "$REPO" \
  --arg branch "$BRANCH" \
  --arg head "$head_oid" \
  --arg headline "$headline" \
  --arg body "$message_body" \
  --argjson additions "$additions" \
  '{
    query: $query,
    variables: {
      input: {
        branch: {repositoryNameWithOwner: $repo, branchName: $branch},
        expectedHeadOid: $head,
        message: {headline: $headline, body: $body},
        fileChanges: {additions: $additions}
      }
    }
  }' | gh api graphql --input - --jq '.data.createCommitOnBranch.commit.oid' \
  | xargs -I{} echo "committed {} (verified)"
