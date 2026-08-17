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
among others) check it out rather than keeping their own copy, so a change here
reaches them — keep guidance consistent across skills, since an agent that
contradicts the skill beside it is worse than no agent.

Validate before opening a PR:

```sh
claude plugin validate .                     # marketplace manifest
claude plugin validate plugins/pegasus-ai    # one plugin
```

## Tools

## pre-commit

```sh
cd claude-plugin-marketplace

# Install pre-commit
pip3 install -U pre-commit

# Install pre-commit hook
pre-commit install
```
