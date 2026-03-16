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
| [pegasus-ai](https://github.com/pegasus-isi/claude-plugin-marketplace/tree/main/plugins/pegasus-ai) | Workflow authoring for Pegasus WMS — generate `workflow.yml` files, experiment configs, and scaffold scientific pipelines with Claude. |
| [impeccable](https://impeccable.style) | Design vocabulary and skills for frontend development. Includes 20 commands (/polish, /distill, /audit, /typeset, /overdrive, etc.) and an enhanced frontend-design skill with curated anti-patterns. |
| [nano-banana](https://github.com/buildatscale-tv/claude-code-plugins) | Nano Banana image generation supporting Gemini Flash, Pro, and Nano Banana 2 models. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for instructions on how to add or update plugins.

## Funding

Funded by National Science Foundation (NSF) under award [2513101](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2513101).

## License

Apache 2.0 © [Pegasus ISI](https://github.com/pegasus-isi)
