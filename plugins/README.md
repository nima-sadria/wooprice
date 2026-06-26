# WooPrice Beta — Plugin Development Guide

This directory is the plugin development workspace.

## Structure

```
plugins/
├── README.md                         # This file
├── schema/
│   └── plugin_manifest.schema.json   # JSON Schema for plugin manifests
└── examples/
    └── dummy_channel/                # Minimal reference implementation
        ├── plugin.json               # Plugin manifest
        └── adapter.py                # DummyChannelAdapter
```

## Plugin Categories

| Category | Interface | Description |
|---|---|---|
| Source Adapter | `SourceAdapterPlugin` | Custom price data sources |
| Channel Adapter | `ChannelAdapterPlugin` | Custom sales channel sinks |
| Rule Extension | `RuleExtensionPlugin` | Custom transformation rules |
| Safety Policy Extension | `SafetyPolicyPlugin` | Custom safety constraints |
| UI Module | `UIModulePlugin` | Additional frontend pages/widgets |
| Report Module | `ReportModulePlugin` | Custom report generators |

## Getting Started

1. Copy `examples/dummy_channel/` as a starting point
2. Edit `plugin.json` with your plugin's metadata
3. Implement the appropriate interface from `app/beta/plugins/interfaces`
4. Install: `wooprice adapters install --from plugins/your-plugin/`

Full documentation: `docs/beta/PLUGIN_ARCHITECTURE.md`

Implementation of the plugin system begins in B12.
