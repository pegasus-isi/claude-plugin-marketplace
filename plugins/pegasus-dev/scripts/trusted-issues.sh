#!/usr/bin/env bash
# Deterministic trust filter for dispatch-issues' issue scan. Replaces a raw `gh issue list` call
# so the model never sees -- and so can never act on -- an issue whose `claude` label wasn't
# applied by someone with at least PEGASUS_DEV_MIN_LABEL_PERMISSION (default: write) access to the
# repo. GitHub only requires "triage" role to label/assign an issue, and an issue template's
# `labels:`/`assignees:` frontmatter auto-applies both to any issue at creation regardless of the
# creator's permission -- neither is sufficient authorization for autonomous code changes.
#
# Usage:
#   trusted-issues.sh list <owner/repo> <assignee-login>
#     Prints (stdout) the JSON array of open, claude-labeled issues assigned to <assignee-login>
#     whose *most recent* claude-label-add event was performed by an actor at or above
#     PEGASUS_DEV_MIN_LABEL_PERMISSION. Same shape as `gh issue list --json
#     number,title,labels,createdAt`. Excluded issues are reported on stderr as
#     "excluded #<n>: ..." -- never silently dropped. An issue with no detectable claude-labeling
#     event at all is excluded (fail closed).
set -euo pipefail

CMD="${1:-}"
REPO="${2:-}"
ASSIGNEE="${3:-}"
MIN_PERMISSION="${PEGASUS_DEV_MIN_LABEL_PERMISSION:-write}"

# Ranks GitHub's collaborator permission levels so "at least write" is a numeric comparison.
# Unrecognized values (including "none") rank below everything -- fail closed.
perm_rank() {
  case "$1" in
    admin) echo 4 ;;
    maintain) echo 3 ;;
    write) echo 2 ;;
    triage) echo 1 ;;
    read) echo 0 ;;
    *) echo -1 ;;
  esac
}

case "$CMD" in
  list)
    [[ -n "$REPO" && -n "$ASSIGNEE" ]] || {
      echo "usage: trusted-issues.sh list <owner/repo> <assignee-login>" >&2
      exit 2
    }
    MIN_RANK="$(perm_rank "$MIN_PERMISSION")"

    ISSUES="$(gh issue list --repo "$REPO" --label claude --assignee "$ASSIGNEE" --state open \
      --json number,title,labels,createdAt)"

    KEPT="[]"
    while IFS= read -r ISSUE; do
      [[ -z "$ISSUE" ]] && continue
      NUM="$(jq -r '.number' <<<"$ISSUE")"

      # Actor of the most recent "claude" label-add event -- re-labeling after a maintainer
      # removes it re-authorizes correctly; no such event at all fails closed below.
      ACTOR="$( (gh api "repos/$REPO/issues/$NUM/timeline" --paginate 2>/dev/null || echo '[]') |
        jq -r '[.[] | select(.event=="labeled" and .label.name=="claude")] | last | .actor.login // empty' )"

      if [[ -z "$ACTOR" ]]; then
        echo "excluded #$NUM: no detectable 'claude' label event -- failing closed" >&2
        continue
      fi

      # 404 (actor isn't a collaborator at all) is an expected outcome here, not an error --
      # falls back to an empty object, which yields permission "none" below.
      PERM="$( (gh api "repos/$REPO/collaborators/$ACTOR/permission" 2>/dev/null || echo '{}') |
        jq -r '.permission // empty' )"
      PERM="${PERM:-none}"
      RANK="$(perm_rank "$PERM")"

      if [[ "$RANK" -ge "$MIN_RANK" ]]; then
        KEPT="$(jq -c --argjson issue "$ISSUE" '. + [$issue]' <<<"$KEPT")"
      else
        echo "excluded #$NUM: claude label added by $ACTOR (permission=$PERM, need >= $MIN_PERMISSION)" >&2
      fi
    done < <(jq -c '.[]' <<<"$ISSUES")

    echo "$KEPT"
    ;;

  *)
    echo "usage: trusted-issues.sh {list} ..." >&2
    exit 2
    ;;
esac
