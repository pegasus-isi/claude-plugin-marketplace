# Contributing

```sh
git clone https://github.com/pegasus-isi/claude-plugin-marketplace.git
```

## Adding or changing a skill or agent

Skills live at `plugins/<plugin>/skills/<name>/SKILL.md`, agents at
`plugins/<plugin>/agents/<name>.md`. Both carry YAML frontmatter with at least
`name` and `description`; consumers read those rather than a separate metadata
file, so a description cannot drift from the thing it describes.

This tree is the single source of truth. Downstream products (PegasusAI Studio,
among others) install it rather than keeping their own copy, so a change here
reaches them — keep guidance consistent across skills, since an agent that
contradicts the skill beside it is worse than no agent.

Validate before opening a PR:

```sh
claude plugin validate .                     # marketplace manifest
claude plugin validate plugins/pegasus-ai    # one plugin
```

## Packaging

The tree also ships as the `pegasus-ai-knowledge` Python package, for hosts that
cannot clone it at runtime.

```sh
python -m build --wheel
python scripts/check_wheel_contents.py dist/*.whl
```

**An untracked file under `plugins/` ships to everyone who installs the
package.** Hatchling's `force-include` reads the working tree, not the git
index, so a draft skill left lying around is published. `check_wheel_contents.py`
fails the build when that happens, and CI runs it — but it is worth knowing
before you leave scratch work in the tree.

`.cz.toml` owns the version; `cz bump` updates `pyproject.toml` and
`src/pegasus_ai_knowledge/__init__.py` together.

## Tools

## pre-commit

```sh
cd claude-plugin-marketplace

# Install pre-commit
pip3 install -U pre-commit

# Install pre-commit hook
pre-commit install
```
