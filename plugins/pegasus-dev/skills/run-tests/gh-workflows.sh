#!/usr/bin/env bash
# Monitor GitHub Actions runs that were auto-triggered (push/pull_request) for a
# branch — never dispatches a run. Waits for the matching run(s) to complete and
# reports success/failure.
#
# Usage: gh-workflows.sh [BRANCH] [SHA]
set -euo pipefail

BRANCH="${1:-main}"
SHA_FILTER="${2:-}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [[ ! -d "$REPO_ROOT/.github/workflows" ]]; then
  echo "No .github/workflows found at repo root ($REPO_ROOT) — this repo isn't configured for GitHub Actions. Skipping." >&2
  exit 1
fi

echo "Waiting for auto-triggered runs (push/pull_request) on branch '$BRANCH'${SHA_FILTER:+ at $SHA_FILTER}..."

RUN_IDS=()
for i in $(seq 1 30); do
  ROWS="$(gh run list --branch "$BRANCH" --limit 50 \
    --json databaseId,event,headSha,workflowName |
    jq -r --arg sha "$SHA_FILTER" \
      '.[] | select(.event=="push" or .event=="pull_request") | select($sha=="" or .headSha==$sha) | .databaseId')"
  if [[ -n "$ROWS" ]]; then
    mapfile -t RUN_IDS <<<"$ROWS"
    break
  fi
  sleep 10
done

if [[ ${#RUN_IDS[@]} -eq 0 ]]; then
  echo "No auto-triggered run found for branch '$BRANCH'${SHA_FILTER:+ at $SHA_FILTER} after 5 minutes." >&2
  echo "Push the commit (or open the PR) first — this script only watches, it never triggers." >&2
  exit 1
fi

echo "Monitoring ${#RUN_IDS[@]} run(s): ${RUN_IDS[*]}"

FAILED=0
for RUN_ID in "${RUN_IDS[@]}"; do
  while true; do
    STATUS=$(gh run view "$RUN_ID" --json status --jq '.status')
    echo "Run $RUN_ID status: $STATUS"
    [[ "$STATUS" == "completed" ]] && break
    sleep 10
  done

  CONCLUSION=$(gh run view "$RUN_ID" --json conclusion --jq '.conclusion')
  echo "Run $RUN_ID conclusion: $CONCLUSION"

  if [[ "$CONCLUSION" != "success" ]]; then
    FAILED=1
    echo
    echo "=================================================="
    echo "FAILED RUN $RUN_ID"
    echo "=================================================="
    gh run view "$RUN_ID" --log-failed
    echo
  fi
done

exit $FAILED
