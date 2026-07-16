---
name: ship
description: Orchestrate the full Pegasus dev pipeline for the current change — unit tests, review, commit, push, e2e, PR — pausing at gates. Use ONLY when the user explicitly asks to ship / run the whole pipeline / take a change through to PR, or invokes /ship [--base <branch>]. Commits, pushes, and runs CI, so never run without an explicit request.
---

Drive the current change through the team pipeline. Pause for explicit confirmation at each
**GATE**.

First check state: `git branch --show-current`, `git status --short`.

**Base branch `<base>`:** use `--base <branch>` if passed; else derive from the current branch —
second-to-last `/`-segment if it looks like a version (e.g. `5.1`), otherwise `main`. Pass
`<base>` through to the `review` and `pr` steps so the diff and PR target the right branch.

1. **Unit tests** — invoke the `test-pkg` skill for the changed package(s). Must pass before continuing.
2. **Review** — invoke the `review` skill (with `<base>`): simplify + security + general (Claude) +
   Codex review + Codex adversarial.
   **GATE:** present the consolidated findings, let the user choose fixes, apply them. Re-run if needed.
3. **Commit** — invoke the `commit` skill (commitizen format, `Refs #<n>`).
4. **Push** — **GATE:** confirm, then `git push -u origin <branch>` (guardrail enforces a feature
   branch, not main).
5. **e2e** — wait ~30s for the GitHub→GitLab mirror, then run in the **background**:
   `.claude/skills/run-tests/glab-pipeline.sh <branch> workflow`
   This takes **hours** and uses shared CI runners. **GATE:** confirm before launching. Note the
   `Pipeline ID`.
6. **Decision** — when e2e finishes: if it **exited 0**, proceed. If it failed, surface the
   failed-job traces and **STOP — do not open a PR.**
7. **PR** — only on e2e success, invoke the `pr` skill (with `<base>`).

Report a short summary of what ran and the final PR URL (or where it stopped and why).
