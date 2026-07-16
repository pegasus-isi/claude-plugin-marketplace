---
name: dispatch-issues
description: Loop A of the autonomous Pegasus dev pipeline — scan claude-labeled issues assigned to you that don't have a PR yet, resume whichever one is in flight, or start the oldest queued one. Designed as a /loop target, runs independently of dispatch-prs (which takes over once a PR exists). Use when invoked by /loop, or standalone for a single dry-run pass.
model: sonnet
effort: low
allowed-tools: Bash(gh issue view:*), Bash(gh issue edit:*), Bash(gh issue develop:*), Bash(gh repo view:*), Bash(gh api:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/trusted-issues.sh:*), Read, Agent
---

Run ONE pass and stop. Stateless — re-derive everything from GitHub/local git every pass, never
trust conversation memory. This skill runs inside a long-lived `/loop` session, so the
conversation may already contain your own summaries from earlier passes — treat those as history
only. Even if you recall a conclusion from a prior pass ("no PR yet", "nothing actionable"),
re-run every detector command below fresh this pass and act only on its current output — a human
can act between wakeups, so a conclusion from 10 minutes ago may already be stale. **Single
writer:** exactly one `dispatch-issues` loop session may run at a time. Runs independently of
`dispatch-prs` — once an issue has a PR (open or merged), this skill stops touching it;
`dispatch-prs` owns it from there.

Strictly serial: at most one issue without a PR yet is ever in flight. This is what keeps the
skill simple — there is no slot-classification or concurrency bookkeeping to get wrong.

## Pass

1. **Scan**: `${CLAUDE_PLUGIN_ROOT}/scripts/trusted-issues.sh list "$(gh repo view --json
   nameWithOwner --jq .nameWithOwner)" "$(gh api user --jq .login)"` — a deterministic trust
   filter, not a plain query: it excludes any issue whose `claude` label wasn't added by an actor
   with at least `PEGASUS_DEV_MIN_LABEL_PERMISSION` (default `write`) permission on the repo.
   This matters because GitHub only requires **triage** role to label/assign an issue, and an
   issue template's `labels:`/`assignees:` frontmatter can auto-apply both at creation regardless
   of the creator's permission — without this filter, a random person could get an issue
   autonomously implemented and pushed. Never substitute a raw `gh issue list` call here; this
   skill has no `gh issue list` in its `allowed-tools` for exactly that reason — the trust check
   is a tool-level boundary, not a step the model could choose to skip. `--assignee` scoping
   happens inside the script exactly as before: an issue with the `claude` label but assigned to
   someone else (or unassigned) is out of scope, same as if it had no `claude` label at all. The
   script reports excluded issues (number + untrusted actor) on stderr — surface those verbatim
   in this pass's report so a human notices.
   For each issue the script returns, check for an existing PR **directly** via GraphQL — NOT via
   `gh issue develop --list <n>` → `gh pr list --head <branch>`:
   ```
   gh api graphql -F owner=<owner> -F repo=<repo> -F issue=<n> -f query='
   query($owner:String!,$repo:String!,$issue:Int!){
     repository(owner:$owner,name:$repo){ issue(number:$issue){
       closedByPullRequestsReferences(first:5){ nodes{ number state } } } } }'
   ```
   Any node present (open or merged) → **skip this issue entirely**; it belongs to
   `dispatch-prs` now. (Confirmed live: once a PR exists, GitHub stops surfacing the branch via
   the issue's `linkedBranches`/`gh issue develop --list <n>` — a branch-first lookup can never
   find a PR that already exists, so this must go issue→PR directly.) Only once this comes back
   empty is `gh issue develop --list <n>` a reliable "no branch yet" signal, used below to tell
   queued from in-progress.
2. Among the remaining (no-PR-yet) issues, in this order. If a category below has more than one
   match, act on the **oldest** matching issue only — "strictly serial" means picking exactly
   one issue for the whole pass, not one per category. (Multiple simultaneous matches in one
   category are a real, expected occurrence, not just a drift artifact — e.g. one issue can get
   unblocked and reclaimed as `claude:in-progress` while another is still mid-checkpoint-chain
   from an earlier pass.)
   - **Blocked + answered** (labeled `claude:blocked`, and EITHER a comment exists after the last
     `<!-- claude:question -->` marker comment, OR the issue body itself was edited after that
     marker comment's timestamp — a human sometimes clarifies by editing the issue instead of
     replying):
     ```
     gh api graphql -F owner=<owner> -F repo=<repo> -F issue=<n> -f query='
     query($owner:String!,$repo:String!,$issue:Int!){
       repository(owner:$owner,name:$repo){ issue(number:$issue){
         comments(last:20){ nodes{ body createdAt } }
         userContentEdits(last:5){ nodes{ editedAt } } } } }'
     ```
     Find the marker comment's `createdAt` (`T`); answered ⇔ any comment `createdAt` > `T`, OR
     any `userContentEdits` `editedAt` > `T`. `userContentEdits` tracks only genuine body/title
     content changes — label edits (e.g. this very skill's own `--add-label`/`--remove-label`
     calls) never appear in it, so this can't self-trigger as a false positive.
     → `gh issue edit <n> --remove-label claude:blocked`, then spawn an `issue-worker` subagent
     (fresh context) to run `work-issue <n>` — its clarity gate re-reads the current body, so an
     edited body is picked up automatically once unblocked.
   - **In progress** (labeled `claude:in-progress`) → spawn `issue-worker` to resume
     `work-issue <n>` — the checkpoint chain detects exactly where it left off.
   - **Nothing in flight, and a queued issue exists** (`claude` label only, no linked branch) →
     spawn `issue-worker` on it. If it blocks immediately at its clarity gate (checkpoint 1), try
     the next-oldest queued issue in this same pass — a vague issue shouldn't stall the queue
     until the next wakeup.
   - Skip anything labeled `claude:failed` (terminal until a human removes the label).
3. **Report** one line per tracked issue and what it's waiting on next. Pace the next wakeup to
   match: short (1–3 min) if work just happened or a retry is due soon; longer (20–30 min) if
   only waiting on e2e; longer still (30–60 min) if only waiting on a human reply.
