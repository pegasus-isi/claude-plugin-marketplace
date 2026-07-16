---
name: test-pkg
description: Run a package/directory's unit test suite, auto-detecting the test runner (tox, pytest, npm/yarn/pnpm, make, go test) from what's actually present in it — not hardcoded to any one language or tool. Use when the user asks to run or test a specific package/module's unit tests locally, or invokes /test-pkg <path>.
model: haiku
effort: low
allowed-tools: Bash(export:*), Bash(tox:*), Bash(pytest:*), Bash(npm:*), Bash(yarn:*), Bash(pnpm:*), Bash(make:*), Bash(go:*), Bash(cd:*), Glob, Read
---

Run the unit test suite for a single package/directory, auto-detecting how to run it.

Arguments (from the user's request):
- **Path** — the package/module directory to test, relative to the repo root (e.g.
  `packages/pegasus-api`, `services/worker`, or `.` for the repo root). If none was given, ask.
- **Env/target** (optional) — passed through to whichever runner is detected (a tox env name, a
  Makefile target, etc.). Each runner below has its own default when omitted.

## Detect the runner

Check inside the target path, in this order — first match wins. Never assume tox (or any other
tool) without checking; pick whichever marker is actually there:

1. **`tox.ini`** → `tox` (env: the one given, else `py310` if that env exists in the ini, else
   tox's own default env).
2. **`pyproject.toml` / `setup.cfg` / `pytest.ini`, or a `tests/`/`test/` dir, with no
   `tox.ini`** → `pytest`.
3. **`package.json` with a `scripts.test` entry** → run it via whichever package manager matches
   the lockfile present (`package-lock.json`→npm, `yarn.lock`→yarn, `pnpm-lock.yaml`→pnpm);
   default `npm test` if no lockfile is present.
4. **`Makefile` with a `test:` target** → `make test`.
5. **`go.mod`** → `go test ./...`.
6. None of the above → report "no recognized test runner in `<path>`" and stop; don't guess at one.

## Steps

1. Determine the path (and optional env/target) from the request.
2. Detect the runner per above.
3. **tox only, and only if it actually fails on a missing interpreter**: if a uv-managed CPython
   exists at `$HOME/.local/share/uv/python/cpython-*-*/bin` matching the needed version, prepend
   it to PATH and retry once — some machines have no matching system Python. Don't prepend
   unconditionally; most environments don't need it.
4. `cd <path> && <detected command>`.
5. Report pass/fail; on failure, surface the failing test output.
