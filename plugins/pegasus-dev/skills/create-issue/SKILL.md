---
name: create-issue
description: Create a GitHub issue from the repo's issue template (bug_report/feature_request), typed/labeled/self-assigned, then an issue-linked branch + git worktree off a chosen base. Use when the user asks to create/open/file a new issue, or invokes /create-issue <desc> [--base <branch>].
allowed-tools: Bash(gh issue create:*), Bash(gh issue develop:*), Bash(gh issue view:*), Bash(gh label list:*), Bash(gh repo view:*), Bash(git rev-parse:*), Bash(git fetch:*), Bash(git worktree:*), Bash(uname:*), Bash(sw_vers:*), Bash(cat:*), Bash(python3:*), Read, AskUserQuestion
---

Open a new GitHub issue for what the user described, then set up an issue-linked branch + worktree.

First, gather context:
- `gh repo view --json nameWithOwner -q .nameWithOwner` — the repo
- `gh label list --limit 100 | cut -f1` — available labels
- `ls .github/ISSUE_TEMPLATE` — available templates

**Base branch:** we develop on both `main` and the previous-version branch (e.g. `5.1`).
Default `<base>` = `main`; if the user passed `--base <branch>` or named a target (e.g. "from
5.1"), use that. The created branch forks from `<base>`.

1. **Pick the kind + template.** Infer the kind from the request; if ambiguous, ask with
   AskUserQuestion. Blank issues are disabled (`config.yml`), so always use a template:
   - **Bug** → template `.github/ISSUE_TEMPLATE/bug_report.md`; ensure label `bug`.
   - **Feature** → template `.github/ISSUE_TEMPLATE/feature_request.md`.
   - **Task / other** → no template; a concise body is fine.
2. **Build the body from the template.** `Read` the chosen template file, strip its YAML
   frontmatter, and use its section headings as the body skeleton — replace each placeholder with
   real content from the request. For any **required** section you can't fill, ask the user.
   Sections per template:
   - *Feature:* problem/motivation · desired solution · alternatives considered · additional context.
   - *Bug:* describe the bug · steps to reproduce · expected behavior · **Version Information** ·
     submit directory (optional) · additional context.
   - **Auto-detect the Bug "Version Information"** rather than asking (fill what's detectable, ask
     only for the rest):
     - Pegasus version — `bin/pegasus-version`, or the `pegasus.version` key in `build.properties`
     - OS + version — `sw_vers` (macOS) / `cat /etc/os-release` / `uname -a`
     - Python version — `python3 --version`
3. **Title / labels / assignee.**
   - Title — concise, imperative summary.
   - Labels — the template's default (`bug` for bug reports) plus any matching the request.
   - Assignee — `@me` unless the user named someone else.
4. **Create the issue** (pass the filled template body via a heredoc / `--body-file` to preserve
   markdown and newlines):
   ```
   gh issue create --title "<title>" --body "<filled template body>" --type "<Type>" --label "<labels>" --assignee @me
   ```
   If this `gh` version rejects `--type`, create without it and set the type via the GraphQL
   `updateIssue(issueTypeId:)` mutation, or tell the user to set it in the UI.
5. Capture the new issue number `<n>` from the create output.
6. **Create the issue-linked branch** off `<base>` (populates the Development field) — do **not**
   check it out. `<type>` = lowercased issue type (Feature→`feature`, Bug→`bug`, Task→`task`);
   `<slug>` = kebab-cased title. Branch name `<branch>`:
   - base = `main` → `<type>/<n>-<slug>`
   - base ≠ `main` → `<type>/<base>/<n>-<slug>` (e.g. `feature/5.1/1234-add-retry`)
   ```
   gh issue develop <n> --base <base> --name "<branch>"
   ```
7. **Create a git worktree** for the new branch (use the last segment `<n>-<slug>` as the flat
   worktree dir name):
   ```
   git fetch origin "<branch>"
   git worktree add ".claude/worktrees/<n>-<slug>" "<branch>"
   ```
8. Confirm: print the issue URL, the branch name, and the **worktree path** (work happens there).
