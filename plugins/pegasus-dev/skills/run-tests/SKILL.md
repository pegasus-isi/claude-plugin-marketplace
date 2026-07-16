---
name: run-tests
description: Trigger and wait for CI on GitLab (scitech-gitlab.isi.edu), or monitor already auto-triggered CI on GitHub Actions — run unit tests, or run e2e/workflow tests. Which one runs depends on the repo — a `.gitlab-ci.yml` at the repo root uses GitLab, a `.github/workflows` directory uses GitHub Actions. Use when asked to run CI, run e2e tests, run the pipeline, trigger a build, run unit tests on a branch, or wait for CI to pass/fail. e2e (type=workflow) takes hours; run it minimally.
model: haiku
effort: low
allowed-tools: Bash(glab pipeline run:*), Bash(glab api:*), Bash(glab auth status:*), Bash(jq:*), Bash(.claude/skills/run-tests/glab-pipeline.sh:*), Bash(./glab-pipeline.sh:*), Bash(gh run list:*), Bash(gh run view:*), Bash(gh auth status:*), Bash(.claude/skills/run-tests/gh-workflows.sh:*), Bash(./gh-workflows.sh:*)
---

# Run Pegasus CI pipelines (unit / e2e)

Two drivers, chosen by what's actually configured in the repo (paths below are
relative to the repo root):

- **`.claude/skills/run-tests/glab-pipeline.sh`** — if `.gitlab-ci.yml` exists
  at the repo root. Triggers a GitLab CI pipeline via `glab`, polls to
  completion, dumps the trace of every failed job.
- **`.claude/skills/run-tests/gh-workflows.sh`** — else, if `.github/workflows`
  exists. Dispatches every workflow file in that directory via `gh`, polls each
  run to completion, dumps logs for every failed run.

If neither exists, there's no CI configured for this repo — say so rather than
guessing.

## GitLab (`.gitlab-ci.yml`)

```
.claude/skills/run-tests/glab-pipeline.sh [BRANCH] [TYPE]
```

- `BRANCH` — branch/ref to run on. Default: `main`.
- `TYPE` — `workflow` runs the **e2e/workflow** suite (sets pipeline variable
  `CI_PIPELINE_NAME=workflow`). **Anything else or omitted runs unit tests only.**

Exit code: `0` = pipeline succeeded, `1` = failed/canceled/skipped (traces of
failed jobs printed to stdout).

> **e2e (`TYPE=workflow`) takes HOURS. Run it minimally** — only when explicitly
> asked for e2e/workflow tests. Default to unit tests otherwise.

### Prerequisites

- A `.gitlab-ci.yml` file at the repo root. The script checks for this before
  triggering anything and exits 1 if it's missing — GitLab CI only runs for
  repos actually configured for it.
- An `origin` remote in `.git/config` pointing at GitLab. The script reads
  `git config --get remote.origin.url` and derives `owner/repo` from it (works
  for both SSH and HTTPS remote URLs) — it no longer hardcodes a repo.
- `glab` authenticated to **scitech-gitlab.isi.edu** (resolved against the
  configured host, NOT gitlab.com). Check: `glab auth status`.
- `jq` on PATH.

```bash
# macOS
brew install glab jq
glab auth login --hostname scitech-gitlab.isi.edu   # only if not already logged in
```

### Run (agent path)

The script **blocks** while polling (`sleep 10` loop). Unit pipelines finish in
minutes; e2e runs for hours. Launch it in the **background** so you're notified
on exit instead of holding the turn.

Unit tests (default, fast):

```bash
.claude/skills/run-tests/glab-pipeline.sh main
```

e2e / workflow tests (slow — hours — only when explicitly requested):

```bash
.claude/skills/run-tests/glab-pipeline.sh main workflow
```

When launching via the Bash tool, set `run_in_background: true` for e2e (and for
unit runs you don't want to wait on). The script prints `Pipeline ID: <id>` early
— note it. On failure it prints a `FAILED JOB <id>` banner per job followed by
its full trace.

### Check a run without re-triggering

To inspect an already-running/finished pipeline (e.g. the one you just launched)
without firing a new one:

```bash
PID=4677   # from the script's "Pipeline ID:" line
REPO=pegasus-isi/pegasus   # owner/repo — derived from `git config --get remote.origin.url` in this repo
glab api -R "$REPO" projects/:id/pipelines/$PID | jq -r '.status'
# failed-job traces:
glab api -R "$REPO" --paginate projects/:id/pipelines/$PID/jobs \
  | jq -r '.[] | select(.status=="failed") | .id' \
  | while read -r J; do echo "== job $J =="; glab api -R "$REPO" /projects/:id/jobs/$J/trace; done
```

## GitHub Actions (`.github/workflows`)

```
.claude/skills/run-tests/gh-workflows.sh [BRANCH] [SHA]
```

- `BRANCH` — branch to watch. Default: `main`.
- `SHA` — optional commit SHA to pin to; omit to match the latest auto-triggered
  run on the branch.
- **This script never triggers a run.** GitHub Actions has no equivalent of
  GitLab's `CI_PIPELINE_NAME` pipeline variable, and most repos' workflows don't
  declare `workflow_dispatch` (kiso's don't, for example) — so instead of
  dispatching, it finds the run(s) GitHub already started automatically via
  `push` or `pull_request` for the given branch/SHA, and waits for those to
  complete. Runs started any other way (manual `workflow_dispatch`, `schedule`,
  etc.) are ignored.
- Repo is auto-detected by `gh` from the local git remote (same idea as the
  GitLab script's `origin`-URL parsing, but `gh` does this natively).

Exit code: `0` = every matched run succeeded, `1` = at least one failed, or none
were found within the wait window (logs for every failed run printed to stdout).

### Prerequisites

- A `.github/workflows` directory at the repo root containing at least one
  workflow file. The script checks for this and exits 1 if it's missing.
- `gh` authenticated: `gh auth status`.
- A push or PR must already exist for the branch/SHA — this script watches,
  it doesn't create the work. Push the commit (or open the PR) before running it.

### Run (agent path)

Same blocking/polling shape as the GitLab script — launch with
`run_in_background: true` if you don't want to wait on it, or if the matched
workflow is long-running.

```bash
.claude/skills/run-tests/gh-workflows.sh main
```

The script polls for a matching auto-triggered run (up to 5 minutes) and prints
`Monitoring N run(s): <ids>` once found, then polls each to completion. On
failure it prints a `FAILED RUN <id>` banner per run followed by its failed-step logs.

## Gotchas

- **e2e is hours-long (GitLab).** Never trigger `workflow` to "just check" — it
  consumes shared CI runners for hours. Use unit (no `TYPE`) for routine
  checks; reserve `workflow` for explicit e2e requests.
- **GitHub has no unit/e2e split.** `gh-workflows.sh` monitors every
  auto-triggered run it finds on the branch — if one of the repo's workflows is
  a long-running e2e suite, watching "CI" on this repo means waiting on that too.
- **Wrong GitLab host = silent confusion.** `glab` must be authed to
  `scitech-gitlab.isi.edu`. If it's only logged into gitlab.com, the derived
  `-R owner/repo` resolves against the wrong host. Verify with `glab auth status`.
- **`REPO` comes from `origin`, specifically.** The script reads
  `remote.origin.url` — if the repo's real remote is named something else
  (`upstream`, etc.) or `origin` points at a fork, the derived `owner/repo`
  will be wrong. Check with `git remote -v` if the target repo looks off.
- **Mutating `glab api` is blocked by policy.** `allowed-tools` permits only
  `glab pipeline run`, `glab api` (reads), and `glab auth status`; so the skill
  can read pipelines/jobs/traces but never POST/PUT/DELETE. If you genuinely need
  a write, run it yourself outside the skill.
- **No mutating GitHub calls.** `gh-workflows.sh` only reads (`gh run list` /
  `gh run view`); `allowed-tools` doesn't grant `gh workflow run` since nothing
  is ever dispatched.
- **Traces only dump on failure.** GitLab: `canceled`/`cancelled`/`skipped`
  exits 1 with no traces — re-check the pipeline in the UI/API if so. GitHub:
  same idea — a run that isn't `success` gets its failed-step logs dumped, but
  a `cancelled` run may have little useful log output.
- **Ambiguous matches without a SHA.** If several auto-triggered runs exist for
  a branch (e.g. multiple pushes in flight, or both a `push` and a `pull_request`
  run for the same commit), the script monitors every match it finds within the
  wait window. Pass `SHA` to pin to one commit if that's not what you want.
- **`TYPE` arg under `set -u`:** `glab-pipeline.sh` uses `set -euo pipefail`.
  The type arg is read as `${2:-}` so omitting it is safe (`./glab-pipeline.sh
  main` works, i.e. `.claude/skills/run-tests/glab-pipeline.sh main`). If you
  see `line 4: 2: unbound variable`, the script was reverted to `${2}` —
  change it back to `${2:-}`.

## Troubleshooting

- `No .gitlab-ci.yml found` → this repo isn't wired up for GitLab CI; the
  script refuses to trigger a pipeline. Confirm you're in the right repo/root.
- `No .github/workflows found` → this repo isn't wired up for GitHub Actions;
  same idea, other driver.
- `unbound variable` at line 4 → `glab-pipeline.sh` has `TYPE="${2}"`; must be
  `${2:-}`.
- `glab: command not found` / API 401 → `glab auth status`, re-login to
  scitech-gitlab.isi.edu.
- Pipeline ID comes back empty → the `glab pipeline run` output format changed;
  inspect raw output: `glab pipeline run -R pegasus-isi/pegasus --branch main`
  (substitute your repo's actual `owner/repo`).
- `No 'origin' remote found` → `.git/config` has no `origin` remote (or none
  configured); add one or check `git remote -v`.
- `gh: command not found` / API 401 → `gh auth status`, re-login with
  `gh auth login`.
- `No auto-triggered run found ... after 5 minutes` → confirm the commit was
  actually pushed (or the PR opened) before running the script; check manually
  with `gh run list --branch <branch>`.
