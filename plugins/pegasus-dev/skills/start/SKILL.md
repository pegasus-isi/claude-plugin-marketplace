---
name: start
description: Start work on an existing GitHub issue — create an issue-linked branch (via gh issue develop) and a git worktree, off a chosen base. Use when the user asks to start/begin work on an issue, or invokes /start <issue#> [--base <branch>].
model: haiku
effort: low
allowed-tools: Bash(gh issue view:*), Bash(gh issue develop:*), Bash(git rev-parse:*), Bash(git fetch:*), Bash(git worktree:*)
---

Begin work on an existing GitHub issue. The user provides the **issue number** `<n>` and an
optional `--base <branch>`.

First, read the issue: `gh issue view <n> --json number,title,body,labels,issueType` (fall back to
without `issueType` if that field is unsupported). Summarize it (title, type, what needs doing).

**Base branch:** we develop on both `main` and the previous-version branch (e.g. `5.1`).
Default `<base>` = `main`; if the user passed `--base <branch>` or named one (e.g. "from 5.1"),
use that. Fork point, review diff, and PR target all follow `<base>`.

Steps:
1. Derive the branch **type prefix** from the issue type (Feature→`feature`, Bug→`bug`,
   Task→`task`; default `task`) and a kebab-case `<slug>` from the title. Branch name `<branch>`:
   base = `main` → `<type>/<n>-<slug>`; base ≠ `main` → `<type>/<base>/<n>-<slug>`.
2. Create the linked branch off `<base>` (populates the issue's Development field) — do **not**
   check it out:
   ```
   gh issue develop <n> --base <base> --name "<branch>"
   ```
3. Create a **git worktree** for it (use the last segment `<n>-<slug>` as the flat dir name):
   ```
   git fetch origin "<branch>"
   git worktree add ".claude/worktrees/<n>-<slug>" "<branch>"
   ```
4. Confirm the branch name and the **worktree path** (work happens there).
