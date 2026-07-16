---
name: pr
description: Open a GitHub PR for the current branch, targeting its base — only after e2e passes (or isn't configured at all). Use ONLY when the user explicitly asks to open/create a pull request, or invokes /pr [--base <branch>] [--review-ledger <findings>]. Invocation by an orchestrating skill (ship, work-issue, dispatch-issues) counts as an explicit request. Pushes the branch, so do not run otherwise.
model: sonnet
effort: medium
allowed-tools: Bash(gh pr create:*), Bash(gh pr view:*), Bash(gh pr list:*), Bash(git push:*), Bash(git branch:*), Bash(git log:*), Bash(git ls-remote:*), Bash(git rev-parse:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh:*), AskUserQuestion
---

Open a GitHub pull request for the current branch.

First check the branch: `git branch --show-current`.

**Base branch `<base>`:** use `--base <branch>` if passed; else derive from the current branch —
if its second-to-last `/`-segment looks like a version (e.g. `5.1`), that's `<base>`; otherwise
`<base>` = `main`. The PR targets `<base>` (NOT always main). Review the commits with
`git log --oneline origin/<base>..HEAD`.

**Precondition — e2e must be green, or not configured at all.** Verify yourself — never just
trust the invoker's claim. Call `${CLAUDE_PLUGIN_ROOT}/scripts/e2e.sh status <branch> <head-sha>`
(head-sha from `git ls-remote origin <branch>`); it abstracts over whatever CI is actually
configured (GitLab, GitHub Actions, or neither):
- `unconfigured` → no CI is configured for this repo at all — proceed.
- `<id> success <sha>` where `<sha>` matches the head — proceed.
- If the `ship` skill already ran e2e in this session and it passed, proceed (ship uses its own
  interactive `run-tests` path, not `e2e.sh`).
- Anything else (running/pending/failed, or a mismatched sha) → **refuse**. If invoked directly
  by a human with no e2e run yet, tell them to run e2e first (the `run-tests` skill with
  `<branch> workflow`). If invoked by an orchestrator, this shouldn't happen — report the
  mismatch and stop rather than opening the PR anyway.

Steps:
1. Push the branch: `git push -u origin <branch>` (the guardrail blocks main/force-push; you are
   on a feature branch).
2. Determine the issue number `<n>` — the leading digits of the last `/`-segment of the branch
   name (e.g. `feature/5.1/1234-add-retry` → `1234`).
3. Open the PR against `<base>`, assigned to `@me`, with a body summarizing the commits and
   `Closes #<n>` so merging closes the issue. If the invoker passed `--review-ledger <findings>`
   (a non-empty list of quality-gate findings that were autonomously reviewed but not auto-fixed
   — skipped as judgment/stylistic calls), add a `## Skipped review findings` section listing
   them, so a human reviewer knows what to look at:
   ```
   gh pr create --base <base> --assignee @me --title "<title>" --body "<summary>

   ## Skipped review findings
   <one bullet per ledger entry — only if the ledger is non-empty>

   Closes #<n>"
   ```
4. Print the PR URL.
