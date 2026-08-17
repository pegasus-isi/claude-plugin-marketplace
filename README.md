<p align="center">
  <img width="50%" alt="scitech-claude-code-plugin-marketplace" src="https://github.com/user-attachments/assets/8e229427-3bbe-4cc1-83fb-d109db278f1f" />
</p>

# SciTech Claude Code Plugin Marketplace

> A curated collection of Claude Code plugins for scientific computing — built for researchers and developers working with Pegasus WMS and SciTech infrastructure.

![License](https://img.shields.io/github/license/pegasus-isi/claude-plugin-marketplace.svg?logo=apache&color=blue&label=License)
![Contributors](https://img.shields.io/github/contributors-anon/pegasus-isi/claude-plugin-marketplace?color=green&label=Contributors)

## What Is This?

[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) plugins extend the Claude Code CLI with domain-specific skills, MCP servers, and AI-assisted workflows. This marketplace provides plugins tailored for scientific computing — including Pegasus WMS workflow authoring and SciTech project development.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) CLI installed

## Quick Start

Add the marketplace and install a plugin in two commands:

```bash
/plugin marketplace add pegasus-isi/claude-plugin-marketplace
/plugin install <plugin-name>@scitech
```

## Installation

### Option 1: Claude Code CLI (recommended)

Run the following commands from within Claude Code:

```bash
/plugin marketplace add pegasus-isi/claude-plugin-marketplace
/plugin install <plugin-name>@scitech
```

### Option 2: Manual configuration

Add the following to your `.claude/settings.json` file:

```json
{
  "extraKnownMarketplaces": {
    "scitech": {
      "source": {
        "source": "github",
        "repo": "pegasus-isi/claude-plugin-marketplace"
      }
    }
  },
  "enabledPlugins": {
    "<plugin-name>@scitech": true
  }
}
```

## Available Plugins

| Plugin | Description |
|--------|-------------|
| [pegasus-dev](https://github.com/pegasus-isi/claude-plugin-marketplace/tree/main/plugins/pegasus-dev) | Skills and tools for developing software on SciTech projects — git workflows, code review, commit conventions, and project-specific best practices. |
| [pegasus-ai](https://github.com/pegasus-isi/claude-plugin-marketplace/tree/main/plugins/pegasus-ai) | Workflow authoring for Pegasus WMS — generate `workflow.yml` files, experiment configs, and scaffold scientific pipelines with Claude, plus specialist subagents for workflow design, data engineering, and failure diagnosis. |
| [impeccable](https://impeccable.style) | Design vocabulary and skills for frontend development. Includes 20 commands (/polish, /distill, /audit, /typeset, /overdrive, etc.) and an enhanced frontend-design skill with curated anti-patterns. |

## Installing without git

Some hosts cannot clone this repo at runtime: a container image built ahead of
time, an Open OnDemand app, an HPC login node with no outbound network. For
those, the same tree ships as a Python package.

```sh
pip install pegasus-ai-knowledge
```

The package contains the marketplace directory verbatim, so there is still only
one authored copy of every skill and agent. Point Claude Code at it with a seed
directory:

```sh
export CLAUDE_CODE_PLUGIN_SEED_DIR="$(pegasus-ai-knowledge seed ~/.local/state/pegasus-ai/seed)"
export CLAUDE_CODE_PLUGIN_CACHE_DIR=~/.local/state/pegasus-ai/plugins
```

Seeded marketplaces are read-only and are skipped during refresh, so nothing is
fetched over the network. Enable the plugins as usual via `enabledPlugins` in a
settings file.

Other commands:

```sh
pegasus-ai-knowledge path [plugin]   # path to a packaged plugin (default: pegasus-ai)
pegasus-ai-knowledge marketplace     # path to the packaged marketplace root
pegasus-ai-knowledge plugins         # plugins declared in the manifest
```

From Python:

```python
import pegasus_ai_knowledge as k

k.plugin_dir()                     # .../marketplace/plugins/pegasus-ai
k.write_seed("/var/lib/pegasus-ai/seed")
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for instructions on how to add or update plugins.

## Funding

Funded by National Science Foundation (NSF) under award [2513101](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2513101).

## License

Apache 2.0 © [Pegasus ISI](https://github.com/pegasus-isi)
