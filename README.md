<p align="center">
  <img width="50%" alt="scitech-claude-code-plugin-marketplace" src="https://github.com/user-attachments/assets/8e229427-3bbe-4cc1-83fb-d109db278f1f" />
</p>

![License](https://img.shields.io/github/license/pegasus-isi/claude-plugin-marketplace.svg?logo=apache&color=blue&label=License)
![Contributors](https://img.shields.io/github/contributors-anon/pegasus-isi/claude-plugin-marketplace?color=green&label=Contributors)

## Usage

There are two ways to user the SciTech Claude Code Plugin Marketplace:

1. To use plugins from the marketplace from within Claude Code, run the following commands:

```bash
/plugin marketplace add pegasus-isi/claude-plugin-marketplace
/plugin install <plugin-name>@scitech
```

2. Modify your `.claude/settings.json` file to include the following:

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

## Plugins

| Plugin | Description |
|--------|-------------|
| [pegasus-dev](https://github.com/pegasus-isi/claude-plugin-marketplace/tree/main/plugins/pegasus-dev) | A Claude plugin for software development on SciTech projects. |
| [pegasus-ai](https://github.com/pegasus-isi/claude-plugin-marketplace/tree/main/plugins/pegasus-ai) | A plugin for creating Pegasus WMS workflows with Claude Code. |

# Funding

Funded by National Science Foundation (NSF) under award [2513101](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2513101).
