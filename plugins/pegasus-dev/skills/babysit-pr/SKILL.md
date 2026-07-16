---
name: babysit-pr
description: Autonomously tend one open pegasus PR until merged — address inline review threads, review summaries, and conversation comments (fix → commit → push → re-run e2e → reply), resolve base-branch conflicts, fix red checks, and clean up branch/worktree/labels on merge. Use when invoked by the dispatch-prs loop, or when the user invokes /babysit-pr <pr#> for a single PR.
model: sonnet
allowed-tools: Bash(gh pr view:*), Bash(gh pr list:*), Bash(gh pr checks:*), Bash(gh pr comment:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(gh api:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git fetch:*), Bash(git ls-remote:*), Bash(git worktree:*), Bash(git branch:*), Bash(git merge:*), Bash(git push:*), Bash(git rev-parse:*), Bash(glab api:*), Bash(gh run list:*), Bash(gh run view:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh:*), Bash(jq:*), Read, Edit, Write
---

Tend PR `<pr>` for one pass and stop. Stateless: derive everything from GitHub/GitLab each
invocation. **Autonomous mode:** never use AskUserQuestion; talk to humans only via PR replies
and issue comments. Invoking the `lint`, `test-pkg`, and `commit` skills here counts as an
explicit request.

First: `gh pr view <pr> --json state,mergedAt,mergeable,mergeStateStatus,reviewDecision,headRefName,headRefOid,baseRefName,number,url`.
Let `<branch>` = headRefName, `<base>` = baseRefName, `<n>` = leading digits of the last
`/`-segment of `<branch>`. (`mergeable`/`mergeStateStatus` above are computed server-side by
GitHub, so they're accurate regardless of local staleness — but `git fetch origin <base>` now,
before anything below, since §3's `review --auto` and §4's merge both read `origin/<base>`
locally and would otherwise compare against a stale cached ref.)

Also `git fetch origin "<branch>"` now, and if the worktree already exists from an earlier pass,
fast-forward it with `git merge origin/"<branch>"` before touching anything in it (§3 below
already fetches when *creating* a missing worktree — this covers the far more common case where
it already exists). A human can push a commit directly to the PR branch between passes — their
own fix, an amendment, anything — and pulling first means §3-§5 see that commit rather than a
stale local checkout; otherwise this pass could redo a fix the human already made, or commit on
top of a head that no longer matches origin once it tries to push.

## 1. Merged → cleanup (canonical routine — dispatch-prs delegates merged PRs here)

- `git worktree remove ".claude/worktrees/<n>-<slug>"` — if it's dirty, inspect first; only
  `--force` when the changes are clearly disposable (merged work), otherwise report.
- `git branch -D "<branch>"`
- `gh issue edit <n> --remove-label claude:in-progress --remove-label claude` (the issue itself
  closes via the PR's `Closes #<n>`).
- Delete `.claude/state/issue-<n>.json`. Post a final status comment on the issue. **Done.**

## 2. Closed unmerged

Comment on the PR asking about intent, swap the issue's `claude:in-progress` → `claude:failed`,
remove the worktree, keep the branch. **Return.**

## 3. Actionable feedback — three kinds, marker-based detection

Rebuild the worktree first if missing (`git fetch origin "<branch>" && git worktree add ...`).

- **Inline review threads** (file+line comments): fetch via GraphQL —
  ```
  gh api graphql -F owner=<owner> -F repo=<repo> -F pr=<pr> -f query='
  query($owner:String!,$repo:String!,$pr:Int!){
    repository(owner:$owner,name:$repo){ pullRequest(number:$pr){
      reviewThreads(first:100){ nodes{
        id isResolved isOutdated path line
        comments(first:30){ nodes{ databaseId author{login} body createdAt } } } }
      reviews(last:20){ nodes{ state submittedAt body author{login} } } } } }'
  ```
  A thread is **actionable** ⇔ `isResolved == false` AND its last comment does NOT contain
  `<!-- claude:reply -->`. (Marker-based, not author-based — the human and the CLI may share a
  login.) Fix at `path:line` in the worktree, then reply IN the thread:
  `gh api -X POST repos/<owner>/<repo>/pulls/<pr>/comments/<comment_id>/replies -f body=$'<what was done>\n<!-- claude:reply -->'`
  **Never resolve threads yourself** — the reviewer resolves.
- **Review summaries**: a `CHANGES_REQUESTED` review is actionable iff `submittedAt` > the head
  commit's `committedDate` (`gh pr view <pr> --json commits --jq '.commits[-1].committedDate'`).
- **Conversation comments**: actionable if posted after Claude's last push/`claude:reply` and
  requesting a change; answer questions with a plain reply (+ marker) without code changes.

After making fixes: `lint --fix` → `test-pkg` for changed packages → `review --auto --base <base>`
(same autonomous quality gate as `work-issue` checkpoint 4 — code changed in response to a
reviewer still needs the full security/general/Codex passes, not just lint+tests) → re-run `test-pkg` if
review changed code → `commit` skill → push → reply to every addressed thread/comment (with the
marker). If this `review --auto` surfaces skipped findings, post them as a **new PR comment**
(the PR body's `review_ledger` section is fixed at creation — don't try to edit it after the
fact). In `.claude/state/issue-<n>.json`,
increment `review_fix_rounds["<thread id>"]` (the GraphQL `reviewThreads` node `id` from the
query above) each round a given thread is touched; after `MAX_REVIEW_FIX_ROUNDS_PER_THREAD` (2)
rounds on that SAME thread id, reply asking the reviewer for concrete direction and stop
touching that thread — other threads are unaffected, since each has its own counter.

## 4. Base conflicts

`mergeStateStatus == DIRTY` / `mergeable == CONFLICTING` → in the worktree:
`git merge origin/<base>` (already fetched above) — **merge, never rebase** (a force-push
orphans review comments and confuses the GitLab mirror's sha history). Resolve, then the same
lint/test/review/test sequence as §3, commit, push.

## 5. Red GitHub checks

`gh pr checks <pr>` — diagnose failures from logs, fix in the worktree, then the same
lint/test/review/test sequence as §3, commit, push.

## 6. Re-run e2e after any code push

Any push that changed non-doc code invalidates the previous e2e run. Follow `work-issue`
checkpoints 7–8 using `${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh` (shortened to `e2e.sh` below): wait
for mirror sync (`e2e.sh synced <branch>` — a no-op unless GitLab is the configured CI), then
`e2e.sh trigger <branch>` unconditionally — GitLab's `resource_group` on the e2e job serializes
concurrent pipelines, so no slot-granting is needed here, even with several PRs re-triggering
e2e in the same `dispatch-prs` pass. If the repo has no CI configured at all, `status` returns
`unconfigured` — treat the re-run as trivially satisfied and skip straight to declaring the PR
settled. Same `MAX_E2E_ATTEMPTS` (3) cap via `e2e.sh count` (consecutive-failure streak, not a
lifetime total — a green re-run resets it, so routine review-round re-runs never push the branch
toward `claude:failed` on their own). When e2e is green again, note it in a PR comment.

## 7. Nothing actionable

Report "waiting on human review" with the PR URL.

Finish by reporting one line: what was addressed (threads/conflicts/checks), what was pushed,
and what the PR now waits on.
