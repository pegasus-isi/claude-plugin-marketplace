---
name: lint
description: Semantic lint of staged changes for things static analysis misses — spelling/typos, comments that no longer match the code, docstring/signature drift, stale docs & manpages, and house-style idioms (f-strings over .format()/%, logging over print). Use when asked to lint, run /lint, check staged changes for typos or spelling, find stale comments/docs, or review changes for issues ruff/pre-commit won't catch. Report-only; pass --fix for safe mechanical fixes.
model: sonnet
effort: medium
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/skills/lint/scan.sh:*), Bash(bash ${CLAUDE_PLUGIN_ROOT}/skills/lint/scan.sh:*), Bash(git diff:*), Bash(git status:*), Bash(uvx codespell:*), Read, Edit
---

# /lint — semantic linter for Pegasus WMS

`/lint` is a **semantic reviewer**, not another formatter. Pegasus already runs ruff,
ruff-format, black/isort/autoflake, google-java-format and mdformat on every commit
(pre-commit + the GitLab `Lint` job). This skill covers what those *cannot*: defects only a
reader catches — misspellings, comments/docs that drifted from the code, and house-style
idioms a formatter can't reason about.

It is driven by a candidate-gathering script, **`${CLAUDE_PLUGIN_ROOT}/skills/lint/scan.sh`**,
plus LLM-only passes over the staged diff. **Default target is the git staged set**
(`git diff --cached`). Report-only by default; `--fix` applies only safe mechanical fixes.

Explicit paths passed to the scanner are relative to the target repo's root, not the plugin.

## Run (agent path)

1. **Gather mechanical candidates** — run the scanner over the staged set (or pass explicit
   paths to scope it):

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/lint/scan.sh                                   # staged files
   ${CLAUDE_PLUGIN_ROOT}/skills/lint/scan.sh packages/pegasus-python/src/Pegasus/submitdir.py   # explicit path
   ```

   It prints grouped `path:lineno: snippet` sections (spelling, formatting, print). These are
   **candidates** — you confirm or dismiss each (see Gotchas for the false positives).

2. **Read the actual staged changes** for the semantic passes:

   ```bash
   git diff --cached
   ```

3. **Triage + run the semantic checks** below, then assemble the report (format below).

4. **If invoked with `--fix`**: apply only the *mechanical* findings (spelling corrections;
   `.format()`/`%` → f-string where the conversion is trivially safe) via Edit. **Never**
   auto-apply a semantic/judgment finding — those go in the report only.

## Check catalog

### Mechanical (scan.sh surfaces, you confirm)
- **Spelling** — comments, docstrings, identifiers, user-facing strings, and `.rst`/`.md`
  docs. (codespell; falls back to your reading of the diff if codespell is unavailable.)
- **`.format()` / `%` → f-strings** — the repo is overwhelmingly f-strings (1000+ vs ~110).
- **`print()` in library code → `logging`** — `src/Pegasus/cli/` is the sanctioned exception
  and is excluded by the scanner.

### Semantic (LLM-only — read the diff; no script can do these)
- **Comment ⇄ code drift** — comment/docstring claims X but the code does Y; comment
  references a renamed variable/param; stale comment left behind after a refactor.
- **Docstring ⇄ signature drift** — Google-style `:param:`/`:type:`/return don't match the
  actual args or return; a documented `raises` that can't happen, or a raised exception that
  isn't documented.
- **Doc staleness** — changed CLI flags/options, class signatures, or behavior not reflected
  in `doc/sphinx/` (autodoc + sphinx_click manpages), the package `README.md`, or examples.
  Flag example commands/snippets that would no longer run.
- **Misleading names** — `get_*`/`is_*` that mutates; a name that says one unit but the code
  uses another.
- **Error/log quality** — message text that contradicts the actual failure; wrong log level
  (`logging.error` on a normal path); bare `except: pass` that swallows.
- **Copy-paste residue** — a duplicated block where one variable wasn't updated.
- **Magic numbers/strings** — unexplained literals a named constant or comment would clarify.
- **Terminology consistency** — the same concept named differently across code and docs.
- **Stale TODO/FIXME** — markers referencing work that's already done or removed.
- **Hardcoded paths/URLs/secrets** — absolute paths, hostnames, or credentials that belong in
  config.

## Report format

Group by check. One line per finding: `file:line — issue — suggested fix`. Order
high→low confidence. State plainly when a section had no findings. End with a one-line
summary count, e.g. `Summary: 3 spelling, 1 comment-drift, 0 doc-staleness`.

## Gotchas

- **codespell isn't installed directly** — the scanner runs it via `uvx codespell`
  (~1.5s startup). If neither `codespell`, the `codespell_lib` module, nor `uvx` is present,
  the spelling section prints a degrade notice and you cover spelling by reading the diff.
- **codespell exits non-zero when it finds typos** — handled in the script (keys off output,
  not exit status); don't "fix" that with `set -e`.
- **`%`/`.format()` false positives** — many `%` hits are regex, SQL `LIKE`, or strftime
  patterns, not string formatting. The scanner already drops logging-format lines
  (`log.info("%s", x)` is correct lazy logging); confirm the rest before flagging.
- **`print()` under `cli/` is fine** — those are user-facing CLI tools and are excluded.
- **`--fix` is mechanical-only** — applying a semantic finding without human judgment is how
  you introduce bugs. Report them; don't edit them.
- **Empty staged set** — `scan.sh` with nothing staged exits cleanly with a hint; stage files
  (`git add`) or pass explicit paths.
