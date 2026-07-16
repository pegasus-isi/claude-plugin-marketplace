#!/usr/bin/env bash
# Non-blocking e2e helper for the autonomous dev pipeline. Every subcommand returns
# immediately (no polling loops) so a stateless dispatcher can re-derive e2e state each tick.
#
# Auto-detects which CI system is actually configured and speaks its native API — the
# callers (work-issue, babysit-pr) never need to know which one is in play:
#   - .gitlab-ci.yml exists              -> mode=gitlab  (checked first: wins if both exist)
#   - only .github/workflows/*.y*ml      -> mode=github
#   - neither                            -> mode=none    (e2e is trivially satisfied)
#
# Usage:
#   e2e.sh trigger <branch>          Start e2e if the backend needs an explicit trigger
#                                    (gitlab); no-op for github (auto-triggers on push) and
#                                    none (nothing to trigger). Always prints and exits 0.
#   e2e.sh status  <branch> [sha]    Latest e2e outcome for branch (optionally pinned to sha).
#                                    Prints one of:
#                                      unconfigured           -- mode=none, nothing to wait for
#                                      none                   -- mode=gitlab only: never triggered
#                                      - pending <sha>         -- mode=github only: not visible yet
#                                                                 (auto-triggers on push; wait)
#                                      <id> running <sha>
#                                      <id> failed  <sha>
#                                      <id> success <sha>
#                                    gitlab's own richer pipeline vocabulary (created, pending,
#                                    preparing, scheduled, manual, waiting_for_resource -- the
#                                    status a resource_group-queued pipeline sits in) is
#                                    normalized to "running" below so callers only ever see the
#                                    three outcomes above, regardless of backend.
#   e2e.sh trace   <id>              Dump logs/traces of the run/pipeline's failed jobs.
#   e2e.sh count   <branch>          Consecutive failures since the last success on branch,
#                                    most-recent-first (retry-streak cap, NOT a lifetime total
#                                    -- routine passing re-runs don't count against the cap).
#   e2e.sh synced  <branch>          Exit 0 if there's nothing to wait for: mode=none/github
#                                    (no mirror involved) or mode=gitlab and GitHub/GitLab
#                                    branch heads already match. Exit 1 only when gitlab is
#                                    configured and the mirror hasn't caught up yet.
set -euo pipefail

CMD="${1:-}"
ARG="${2:-}"
SHA_FILTER="${3:-}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

has_workflow_files() {
  [[ -d "$REPO_ROOT/.github/workflows" ]] || return 1
  find "$REPO_ROOT/.github/workflows" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) 2>/dev/null | grep -q .
}

if [[ -f "$REPO_ROOT/.gitlab-ci.yml" ]]; then
  MODE="gitlab"
elif has_workflow_files; then
  MODE="github"
else
  MODE="none"
fi

REPO=""
urlenc() { jq -rn --arg v "$1" '$v|@uri'; }

if [[ "$MODE" == "gitlab" ]]; then
  REMOTE_URL="$(git config --get remote.origin.url || true)"
  if [[ -z "$REMOTE_URL" ]]; then
    echo "No 'origin' remote found in .git/config — can't determine the GitLab repo." >&2
    exit 1
  fi
  REPO="$(sed -E 's#^(git@|https?://)([^:/]+)[:/]##; s#\.git$##' <<<"$REMOTE_URL")"
fi

# gitlab only: print "<id> <status> <ref> <sha>" per workflow pipeline for a query string.
# GitLab's ?name= filter needs >=15.11; filter client-side with a per-pipeline variable check
# as a fallback for older instances.
workflow_pipelines() {
  local query="$1"
  local rows
  rows="$(glab api -R "$REPO" "projects/:id/pipelines?${query}&order_by=id&sort=desc&per_page=100" |
    jq -r '.[] | [.id, .status, .ref, .sha, (.name // "")] | @tsv')"
  while IFS=$'\t' read -r id status ref sha name; do
    [[ -z "${id:-}" ]] && continue
    if [[ "$name" == "workflow" ]]; then
      echo "$id $status $ref $sha"
    elif [[ -z "$name" ]]; then
      if glab api -R "$REPO" "projects/:id/pipelines/$id/variables" 2>/dev/null |
        jq -e '.[] | select(.key=="CI_PIPELINE_NAME" and .value=="workflow")' >/dev/null; then
        echo "$id $status $ref $sha"
      fi
    fi
  done <<<"$rows"
}

case "$CMD" in
  trigger)
    [[ -n "$ARG" ]] || { echo "usage: e2e.sh trigger <branch>" >&2; exit 2; }
    case "$MODE" in
      none)   echo "Not configured for CI — nothing to trigger." ;;
      github) echo "GitHub Actions triggers automatically on push — nothing to trigger." ;;
      gitlab)
        echo "Triggering workflow pipeline on branch '$ARG'..."
        PIPELINE_ID=$(glab pipeline run \
          -R "$REPO" \
          --branch "$ARG" --variables "CI_PIPELINE_NAME:workflow" | sed -E 's/.*id: ([0-9]+).*/\1/')
        echo "Pipeline ID: $PIPELINE_ID"
        ;;
    esac
    ;;

  status)
    [[ -n "$ARG" ]] || { echo "usage: e2e.sh status <branch> [sha]" >&2; exit 2; }
    case "$MODE" in
      none)
        echo "unconfigured"
        ;;
      github)
        ROWS="$(gh run list --branch "$ARG" --json databaseId,status,conclusion,headSha --limit 20 2>/dev/null || echo '[]')"
        if [[ -n "$SHA_FILTER" ]]; then
          ROWS="$(jq --arg sha "$SHA_FILTER" '[.[] | select(.headSha == $sha)]' <<<"$ROWS")"
        fi
        if [[ "$(jq 'length' <<<"$ROWS")" -eq 0 ]]; then
          echo "- pending ${SHA_FILTER:--}"
        elif [[ "$(jq '[.[] | select(.status != "completed")] | length' <<<"$ROWS")" -gt 0 ]]; then
          jq -r '[.[] | select(.status != "completed")][0] | "\(.databaseId) running \(.headSha)"' <<<"$ROWS"
        elif [[ "$(jq '[.[] | select(.conclusion != "success")] | length' <<<"$ROWS")" -gt 0 ]]; then
          jq -r '[.[] | select(.conclusion != "success")][0] | "\(.databaseId) failed \(.headSha)"' <<<"$ROWS"
        else
          jq -r '.[0] | "\(.databaseId) success \(.headSha)"' <<<"$ROWS"
        fi
        ;;
      gitlab)
        QUERY="ref=$(urlenc "$ARG")"
        [[ -n "$SHA_FILTER" ]] && QUERY="$QUERY&sha=$SHA_FILTER"
        LATEST="$(workflow_pipelines "$QUERY" | head -n1)"
        if [[ -z "$LATEST" ]]; then
          echo "none"
        else
          awk '{
            status = $2
            if (status != "failed" && status != "success") status = "running"
            print $1, status, $4
          }' <<<"$LATEST"
        fi
        ;;
    esac
    ;;

  trace)
    [[ -n "$ARG" ]] || { echo "usage: e2e.sh trace <id>" >&2; exit 2; }
    case "$MODE" in
      none)   echo "Not configured for CI." >&2; exit 1 ;;
      github) gh run view "$ARG" --log-failed ;;
      gitlab)
        unset PAGER
        glab api -R "$REPO" --paginate "projects/:id/pipelines/$ARG/jobs" | jq '.[] | select(.status=="failed") | .id' |
        while read -r JOB_ID; do
          echo
          echo "=================================================="
          echo "FAILED JOB $JOB_ID"
          echo "=================================================="
          glab -R "$REPO" api "/projects/:id/jobs/$JOB_ID/trace"
          echo
        done
        ;;
    esac
    ;;

  count)
    [[ -n "$ARG" ]] || { echo "usage: e2e.sh count <branch>" >&2; exit 2; }
    case "$MODE" in
      none)
        echo 0
        ;;
      github)
        ROWS="$(gh run list --branch "$ARG" --json status,conclusion --limit 50 2>/dev/null || echo '[]')"
        STREAK=0
        while IFS=$'\t' read -r status conclusion; do
          [[ -z "${status:-}" ]] && continue
          [[ "$status" != "completed" ]] && continue
          case "$conclusion" in
            failure|timed_out) STREAK=$((STREAK + 1)) ;;
            success) break ;;
            *) : ;;  # cancelled/skipped (superseded) — inconclusive, keep walking
          esac
        done < <(jq -r '.[] | [.status, .conclusion] | @tsv' <<<"$ROWS")
        echo "$STREAK"
        ;;
      gitlab)
        STREAK=0
        while read -r id status ref sha; do
          [[ -z "${id:-}" ]] && continue
          case "$status" in
            failed) STREAK=$((STREAK + 1)) ;;
            success) break ;;
            *) : ;;  # canceled/skipped (superseded) or running/pending — inconclusive, keep walking
          esac
        done < <(workflow_pipelines "ref=$(urlenc "$ARG")")
        echo "$STREAK"
        ;;
    esac
    ;;

  synced)
    [[ -n "$ARG" ]] || { echo "usage: e2e.sh synced <branch>" >&2; exit 2; }
    case "$MODE" in
      none|github)
        echo "unconfigured"
        ;;
      gitlab)
        GH_SHA="$(git ls-remote origin "refs/heads/$ARG" | cut -f1)"
        GL_SHA="$(glab api -R "$REPO" "projects/:id/repository/branches/$(urlenc "$ARG")" | jq -r '.commit.id')"
        if [[ -n "$GH_SHA" && "$GH_SHA" == "$GL_SHA" ]]; then
          echo "synced $GH_SHA"
        else
          echo "unsynced github=$GH_SHA gitlab=$GL_SHA"
          exit 1
        fi
        ;;
    esac
    ;;

  *)
    echo "usage: e2e.sh {trigger|status|trace|count|synced} ..." >&2
    exit 2
    ;;
esac
