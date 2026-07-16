---
name: work-issue
description: Autonomously advance one claude-labeled GitHub issue to its next checkpoint — clarity gate, branch+worktree, implement, lint, unit tests, review --auto, commit, push, e2e — with no human gates (questions go to issue comments). Use when invoked by the dispatch-issues loop, or when the user invokes /work-issue <issue#> [--base <branch>] to advance/debug a single issue.
model: sonnet
allowed-tools: Bash(gh issue view:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(gh issue develop:*), Bash(gh pr list:*), Bash(gh api:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git fetch:*), Bash(git ls-remote:*), Bash(git worktree:*), Bash(git rev-parse:*), Bash(git push:*), Bash(git merge:*), Bash(glab api:*), Bash(gh run list:*), Bash(gh run view:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh:*), Bash(jq:*), Read, Edit, Write
---

Advance issue `<n>` to its **next checkpoint** and stop. This skill is a resume-capable
checkpoint chain: every step's completion is detectable from GitHub/GitLab/local git, and every
step is idempotent — invoking it again after a crash, compaction, or token cut-off resumes from
wherever the issue actually is. Never keep state only in conversation memory.

**Autonomous mode:** never use AskUserQuestion. Questions for humans go on the issue as comments.
Invocation of the `start`, `commit`, and `pr` skills by this skill counts as an explicit request.

**Inputs:** issue number `<n>`; optional `--base <branch>` (else derive: second-to-last
`/`-segment of the branch if it looks like a version, e.g. `5.1`, otherwise `main`).

**Local state file** `.claude/state/issue-<n>.json` in the main checkout (NOT the worktree):
`{"impl_attempts": N, "review_fix_rounds": {"<review_thread_id>": N, ...}, "review_ledger": [
"<finding text, file:line, source>", ...]}`. `review_fix_rounds` is keyed per review thread (used
by `babysit-pr`'s PR review loop; a single scalar can't represent "2 rounds on thread A"
independently of "0 rounds on thread B"). `review_ledger` accumulates the skipped-findings ledger
from every `review --auto` pass (checkpoint 4, and `babysit-pr`'s fix loop) so checkpoint 9 can
carry it into the PR body — this is the only way that ledger survives from checkpoint 4 to
checkpoint 9, which may run in a different subagent invocation entirely. Keep the file out of
git (`.git/info/exclude` has `.claude/state/`). If missing, create with `impl_attempts: 0`,
`review_fix_rounds: {}`, `review_ledger: []` — losing it only resets retry counters and ledger.

Before working through checkpoints: `git fetch origin <base>` in the main checkout. Several
checkpoints below compare against `origin/<base>` locally (checkpoints 4, 5, 9; also `review`'s
diff scope) — without a fresh fetch first, those compare against whatever `origin/<base>` last
happened to be cached as, not GitHub's actual current tip (branch creation itself doesn't need
this — `gh issue develop --base <base>` is a server-side call that always forks from the live
tip, regardless of local staleness).

If a branch already exists for this issue (`gh issue develop --list <n>` — the same check
checkpoint 2 uses below), also `git fetch origin "<branch>"` now and, if its worktree already
exists too (checkpoint 3), fast-forward it with `git merge origin/"<branch>"` before touching
anything in it. This matters most right after a blocked issue gets unblocked and resumed — a
human can push a commit directly to the branch (their own partial fix, a clarifying change)
while the issue sat waiting for their reply, and resuming from a stale local checkout risks
redoing that work or committing on top of a head that no longer matches origin once checkpoint 6
tries to push (same reasoning as `babysit-pr`'s equivalent pull-first step).

## Checkpoint chain

Work through the checkpoints in order. For each, run the **detector** first; if already
satisfied, move on. Do the **action** only for the first unsatisfied checkpoint, then continue as
far as possible in this invocation; return when blocked on an external wait (mirror, e2e) or a
terminal state.

0. **Claimed** — detector: issue has `claude:in-progress`.
   Action: `gh issue edit <n> --add-label claude:in-progress`; ensure state file exists.

1. **Clarity gate** — detector: issue not labeled `claude:blocked` AND requirements are clear.
   Read the issue AND all comments (`gh issue view <n> --json title,body,comments,labels`) —
   comments after a `<!-- claude:question -->` marker are answers; fold them in.
   **Unclear iff any of:** no discernible acceptance criteria; ≥2 materially different
   interpretations; needs data/credentials/systems not in the repo; contradicts existing behavior
   without saying that's intentional.
   Action if unclear: post ONE comment with numbered questions, ending with
   "Reply in a comment — I'll pick this up automatically." and the literal marker
   `<!-- claude:question -->` on its own last line; then
   `gh issue edit <n> --add-label claude:blocked --remove-label claude:in-progress`; **return**.
   Max 2 question rounds total (count `claude:question` markers); after that stay BLOCKED and
   leave it to humans — never auto-fail a blocked issue.

2. **Branch linked** — detector: `gh issue develop --list <n>` has a branch matching
   `^(feature|bug|task)/` and containing `<n>-`. Action: invoke the `start` skill for `<n>`
   (with `--base <base>`). `<branch>` = that branch for all later steps.

3. **Worktree exists** — detector: `git worktree list --porcelain` contains `<n>-`.
   Action: `git fetch origin "<branch>" && git worktree add ".claude/worktrees/<n>-<slug>" "<branch>"`.

4. **Implemented + locally green** — detector: `git log origin/<base>..<branch>` shows commits
   AND worktree is clean AND unit tests passed this invocation or later checkpoints already hold.
   Action (all inside the worktree): increment `impl_attempts`; implement the change; then
   - `lint` skill with `--fix` on the staged/changed set;
   - `test-pkg` skill for each changed package's directory (e.g. a change under
     `packages/pegasus-api/` → `test-pkg packages/pegasus-api`; it auto-detects the runner
     inside); must pass;
   - `review` skill with `--auto` and `--base <base>` (applies mechanical/clear-defect fixes,
     skips judgment calls — append its skipped-findings ledger to `review_ledger` in the state
     file, don't overwrite: `babysit-pr` appends to the same list on later fix rounds);
   - re-run `test-pkg` if review changed code.
   If unit tests still fail after `MAX_IMPL_ATTEMPTS` (3) attempts: post a comment explaining
   what was tried and where it fails, swap `claude:in-progress` → `claude:failed`, **return**.
   If the blocker is missing information rather than difficulty: go to checkpoint 1's
   question flow (BLOCKED is recoverable by a reply; FAILED needs label surgery).

5. **Committed** — detector: worktree clean, commits ahead of `origin/<base>`.
   Action: invoke the `commit` skill (commitizen, `Refs #<n>`).

6. **Pushed** — detector: local `<branch>` sha == `git ls-remote origin <branch>` sha.
   Action: `git push -u origin "<branch>"`.

7. **Mirror synced** — detector: `${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh synced <branch>` exits 0.
   A no-op in GitHub-Actions-only or no-CI repos (nothing to mirror — the code's already where
   any CI would run); only genuinely waits when GitLab is the configured CI. Action: none —
   **return** (the next tick re-checks). If unsynced >30 min past the head commit's committer
   date, post a warning comment on the issue — check for a prior warning first, don't repeat it
   every pass; never re-push blindly.

8. **e2e green for head sha** — detector:
   `${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh status <branch> <head-sha>`. (Below, `e2e.sh` is
   shorthand for that path.) The script abstracts over whatever CI is actually configured —
   GitLab if `.gitlab-ci.yml` exists (checked first, so it wins if both exist), GitHub Actions
   if only `.github/workflows` does, or neither — so this checkpoint never needs to know which:
   - `unconfigured` → no CI is configured for this repo at all. Treat as satisfied — continue
     straight to checkpoint 9, there's nothing to wait for.
   - `none` → (GitLab only, nothing triggered yet) `e2e.sh trigger <branch>` and **return**.
     GitHub Actions never returns bare `none` here — it auto-triggers on push, so a run that
     isn't visible yet reports as pending instead (next bullet). Triggering is unconditional:
     GitLab's own `resource_group` on the e2e job (set in `.gitlab-ci.yml`) serializes
     concurrent pipelines, so no Claude-side slot-granting is needed.
   - `<id> running <sha>` / `- pending <sha>` → **return** (next tick re-checks).
   - `<id> failed <sha>` → `e2e.sh trace <id>`, diagnose from the traces, fix in the worktree,
     and resume from checkpoint 4 (the fix goes through lint/tests/review/commit/push again). If
     `e2e.sh count <branch>` ≥ `MAX_E2E_ATTEMPTS` (3) — the CONSECUTIVE failure streak since the
     last success, not a lifetime total, so passing re-runs never count against the cap — post a
     consolidated failure analysis with trace excerpts on the issue, swap `claude:in-progress` →
     `claude:failed`, **return**.
   - `<id> success <sha>` → continue to checkpoint 9.
   Never trust a result for an old sha; never remember pipeline/run IDs across ticks — always
   re-derive from the live API.

9. **PR open** — detector: `gh pr list --head "<branch>" --state open` non-empty.
   Action: re-check the branch is still mergeable into `<base>` (if the base moved during e2e:
   `git merge origin/<base>` in the worktree, resolve, and resume from checkpoint 4 — a new sha
   needs new e2e). Otherwise invoke the `pr` skill with `--base <base>` and `--review-ledger`
   set to the state file's `review_ledger` array (if non-empty) for inclusion in the PR body —
   `pr` re-verifies e2e itself via `e2e.sh`, no need to pass the result through. The PR is then
   owned by `babysit-pr`.

Finish by reporting one line: the checkpoint reached, what the issue is now waiting on, and the
branch/PR/pipeline identifiers involved.
