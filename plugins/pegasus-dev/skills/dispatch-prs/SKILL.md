---
name: dispatch-prs
description: Loop B of the autonomous Pegasus dev pipeline — babysit every open PR for a claude-labeled issue assigned to you (fix review feedback, resolve conflicts, re-test, clean up on merge), one pass over all of them per wakeup. Designed as a /loop target, runs independently of dispatch-issues (which owns an issue before a PR exists). Use when invoked by /loop, or standalone for a single dry-run pass.
model: sonnet
effort: low
allowed-tools: Bash(gh issue list:*), Bash(gh api:*), Read, Agent
---

Run ONE pass over every PR currently in play and stop. Stateless — re-derive everything from
GitHub/GitLab every pass, never trust conversation memory. This skill runs inside a long-lived
`/loop` session, so the conversation may already contain your own summaries from earlier passes
— treat those as history only. Even if you recall a conclusion from a prior pass ("no actionable
threads", "waiting on human review"), re-run every detector command below fresh this pass and act
only on its current output — a human can act between wakeups (e.g. leave a new review comment),
so a conclusion from 10 minutes ago may already be stale. **Single writer:** exactly one
`dispatch-prs` loop session may run at a time. Runs independently of `dispatch-issues` — this
skill only ever looks at issues that already have a PR.

Unlike issue development, babysitting several PRs in the same pass is safe: each PR has its own
worktree, and fixing one doesn't conflict with fixing another.

## Pass

1. **Scan**: `gh issue list --label claude:in-progress --assignee @me --state all --json
   number,createdAt` — **open or closed**. Closed matters here: a merged PR's `Closes #<n>`
   auto-closes the issue, usually before this pass ever runs, so filtering to open issues would
   miss every merge. `--assignee @me` scopes the whole pass the same way it scopes
   `dispatch-issues` — an issue assigned to someone else never becomes a PR this loop touches.
   For each, check for a linked PR **directly** via GraphQL, not via a branch lookup:
   ```
   gh api graphql -F owner=<owner> -F repo=<repo> -F issue=<n> -f query='
   query($owner:String!,$repo:String!,$issue:Int!){
     repository(owner:$owner,name:$repo){ issue(number:$issue){
       closedByPullRequestsReferences(first:5){ nodes{
         number state isCrossRepository headRepository{ nameWithOwner } } } } } }'
   ```
   (Confirmed live: once a PR exists, the issue's `linkedBranches`/`gh issue develop --list <n>`
   goes empty — a branch-first lookup can never find it.) No node → no PR yet, belongs to
   `dispatch-issues`, skip. `babysit-pr` derives the branch, mergeability, etc. straight from
   `gh pr view <pr>` itself, so the branch name never needs resolving here at all.
   **`isCrossRepository == true` → fork PR from an external contributor. Never spawn
   `pr-sitter`** — its branch lives only on the fork, not `origin`, so worktree/lint/test/review
   would either fail unpredictably or, if that ever got "fixed" to properly fetch
   `refs/pull/<pr>/head`, run the fork's own code (tests, etc.) with this pipeline's full
   permissions. Fork PRs are explicitly out of scope; include them in the report as "external PR
   #<pr> on #<n> — needs manual triage" so a human notices, rather than silently ignoring them.
2. For every **merged**, same-repo PR found → spawn a `pr-sitter` subagent (fresh context) to run
   `babysit-pr <pr>` — its cleanup routine removes the worktree/branch and strips labels.
3. For every **open**, same-repo PR found → spawn a `pr-sitter` subagent to run `babysit-pr <pr>`.
   Do all of them this pass, not just one.
4. **Report** one line per PR and what it's waiting on next. Pace the next wakeup: short if a
   fix just landed and needs a re-check soon; longer (30–60 min) if everything is only waiting
   on human review.
