---
name: review
description: Read-only quality gate for the current change — runs simplify, security-review, a general Claude review, Codex review, and Codex adversarial-review against the base branch and consolidates findings. Use when the user asks to review the change/diff before committing, or invokes /review [--base <branch>] [--auto]. Read-only by default; with --auto (orchestrated pipelines) it applies safe fixes autonomously.
model: opus
effort: high
---

Run the read-only quality gate on the current change, **in order**. Do NOT fix anything until the
user chooses what to address.

First check the branch: `git branch --show-current`.

**Base branch `<base>`:** use `--base <branch>` if the user passed one; else derive from the
current branch — if its second-to-last `/`-segment looks like a version (e.g. `5.1`), that's
`<base>`; otherwise `<base>` = `main`. Inspect the change with
`git diff --name-only "$(git merge-base origin/<base> HEAD)"` — diffing against the merge-base
directly (not `origin/<base>...HEAD`) includes uncommitted staged/unstaged changes as well as
committed ones, since `work-issue` checkpoint 4 invokes this *before* the commit step; a
committed-only diff would silently see nothing to review at exactly that point.

1. **Fan out three independent checks in parallel** — in a single message, launch three
   subagents (`Agent` tool, `subagent_type: general-purpose`), each told the current branch,
   `<base>`, and to inspect `git diff origin/<base>...HEAD`, and to return findings as a plain
   list (`file:line` + one-line description):
   - **Simplify** — invoke the `simplify` skill; return its findings verbatim.
   - **Security** — invoke the `security-review` skill; return its findings verbatim.
   - **General** — read the diff directly for correctness issues, logic errors, missed edge
     cases, and whether it satisfies the issue/spec — no named skill, just a careful read.
   Separate subagents means none is biased by having just read another's findings, and all
   three run concurrently instead of one after another.
2. **Codex review** — run `/codex:review --base origin/<base>`; collect its verbatim findings
   (straight, non-adversarial second opinion from a different model).
3. **Adversarial (Codex)** — run `/codex:adversarial-review --base origin/<base>`; collect its
   verdict + findings (Codex returns findings verbatim and applies no edits).
4. Present **one consolidated list** grouped by source (simplify / security / general / codex
   review / adversarial), each finding with `file:line` and a severity.
5. Use AskUserQuestion to ask which findings to fix. Apply only the chosen fixes — never
   auto-apply everything.

**`--auto` mode** (for orchestrated pipelines like `work-issue`): skip AskUserQuestion in step 5.
Autonomously apply findings that are mechanical/safe (spelling, trivially safe idiom fixes) or
clear correctness/security defects with an obvious fix; SKIP judgment/stylistic findings. End
with a ledger of applied vs. skipped findings (the orchestrator records skipped ones in the PR
body). Interactive default behavior is unchanged.
