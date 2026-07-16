---
name: commit
description: Create a single commitizen / Conventional Commits git commit that references the issue number. Use ONLY when the user explicitly asks to commit the staged/working changes (e.g. "commit this", /commit). Invocation by an orchestrating skill (ship, work-issue, babysit-pr, dispatch-issues, dispatch-prs) counts as an explicit request. Never auto-commit otherwise.
model: sonnet
effort: low
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git diff:*), Bash(git commit:*), Bash(git branch:*), Bash(git log:*), AskUserQuestion
---

Create a single git commit using **commitizen / Conventional Commits** format
(`cz_conventional_commits`).

First, inspect the working tree to understand the change:
- `git status`
- `git diff HEAD` (staged + unstaged)
- `git branch --show-current`
- `git log --oneline -10`

**Message format:**

```
<type>(<scope>): <description>

<optional body>

Refs #<n>
```

- `<type>` — one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`,
  `chore`, inferred from the change. Map the branch prefix if present: `feature`→`feat`,
  `bug`→`fix`, `task`→`chore`.
- `<scope>` (optional) — affected component/package (e.g. `api`, `planner`, `kickstart`).
- `<description>` — **required**, concise, imperative subject line.
- **Issue reference** — extract `<n>` as the leading digits of the **last `/`-segment** of the
  branch name (works for both `feature/1234-slug` and `feature/5.1/1234-slug` → `1234`) and add a
  `Refs #<n>` footer. Use `Closes #<n>` only if this commit fully resolves the issue. If the
  branch has no number, ask the user for the issue number — except when invoked by an
  orchestrating skill: then abort with an error instead of asking.

Stage the relevant changes and create the commit. Do not do anything else.
