---
title: "Independent tools and connections"
description: "Configure search providers and MCP servers directly in Meu."
sidebar_label: "Tools and connections"
sidebar_position: 2
---

# Independent tools and connections

Meu no longer uses the Nous Tool Gateway or its hosted connector accounts.
The former subscription, account linking, and managed tool routes have been removed.

## Web search and media

Web search and page extraction remain available through their direct providers,
including the supported keyless search routes. Configure providers in tool settings.
Image, speech, and transcription tools use their own supported providers and credentials.
A retired `nous` provider or `use_gateway: true` setting requires choosing a supported
provider; Meu does not silently switch your billing account.

## MCP servers

Use the Connectors page to manage independently configured MCP servers and
plugin-provided connections. A remote MCP server connects to its own configured
endpoint; it does not pass through a Nous account.

The agent's `manage_connections` tool supports `install`, `enable`, and `authorize`.
Installation uses the bundled MCP catalog; existing server authorization and approval
flows still apply. Tool discovery searches the tools available in the current session.

For command-line setup, use [`hermes mcp`](../../reference/cli-commands.md#hermes-mcp).
See the [MCP configuration reference](../../reference/mcp-config-reference.md) and
[MCP guide](../../guides/use-mcp-with-hermes.md).

## Plugins and skills

Plugin and skill installation remains available through the existing catalog and
configuration pages. Removing hosted connector accounts does not remove local
MCP servers, plugins, skills, or their saved configuration.
