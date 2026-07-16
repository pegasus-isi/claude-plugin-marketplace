#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-main}"
TYPE="${2:-}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [[ ! -f "$REPO_ROOT/.gitlab-ci.yml" ]]; then
  echo "No .gitlab-ci.yml found at repo root ($REPO_ROOT) — this repo isn't configured for GitLab CI. Skipping." >&2
  exit 1
fi

REMOTE_URL="$(git config --get remote.origin.url || true)"
if [[ -z "$REMOTE_URL" ]]; then
  echo "No 'origin' remote found in .git/config — can't determine the GitLab repo." >&2
  exit 1
fi
REPO="$(sed -E 's#^(git@|https?://)([^:/]+)[:/]##; s#\.git$##' <<<"$REMOTE_URL")"

PIPELINE_VARS=()
if [[ "$TYPE" == "workflow" ]]; then
  # Define pipeline variables here
  PIPELINE_VARS=(
    "CI_PIPELINE_NAME:workflow"
  )
fi

# Build glab variable arguments
VAR_ARGS=()
for var in "${PIPELINE_VARS[@]}"; do
  VAR_ARGS+=(--variables "$var")
done

echo "Triggering pipeline on branch '$BRANCH'..."

PIPELINE_ID=$(glab pipeline run \
  -R "$REPO" \
  --branch "$BRANCH" "${VAR_ARGS[@]}" | sed -E 's/.*id: ([0-9]+).*/\1/')

if [[ $? -ne 0 ]]; then
  echo "Pipeline failed to run"
  exit 1
fi

echo "Pipeline ID: $PIPELINE_ID"

# Wait for completion
while true; do
  STATUS=$(glab api -R "$REPO" projects/:id/pipelines/$PIPELINE_ID | jq -r '.status')

  echo "Pipeline status: $STATUS"

  case "$STATUS" in
    success)
      echo "Pipeline succeeded"
      exit 0
      ;;
    failed)
      echo "Pipeline failed"
      break
      ;;
    canceled|cancelled|skipped)
      echo "Pipeline ended with $STATUS"
      exit 1
      ;;
  esac

  sleep 10
done

# Print logs from failed jobs
unset PAGER
glab api -R "$REPO" --paginate projects/:id/pipelines/$PIPELINE_ID/jobs | jq '.[] | select(.status=="failed") | .id' |
while read -r JOB_ID; do
  echo
  echo "=================================================="
  echo "FAILED JOB $JOB_ID"
  echo "=================================================="

  glab -R "$REPO" api /projects/:id/jobs/$JOB_ID/trace

  echo
done

exit 1
