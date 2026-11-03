---
title: "Local Relay and retired usage collection"
description: "Meu local execution tracking, plugin hooks, and removal of the Nous usage collector"
---

# Local Relay and retired usage collection

Meu has removed the built-in Nous shared-metrics collector. The sender, outbox producer,
consent prompts, schemas, collectors, and installer/update reporting hooks are no longer
part of the runtime. Existing `telemetry.shared_metrics` settings are stripped when
configuration is loaded or saved, including legacy opt-in settings.

The old telemetry directory, if present in an existing profile, is not replayed or sent.
This migration does not delete user history, memory, skills, or credentials.

## Local execution tracking

Relay still coordinates local conversations, turns, model calls, and tools. Those runtime
objects serve execution and cancellation. Local diagnostic logs, token accounting, and update
receipts remain available for troubleshooting. None requires the removed usage collector.

[Observer hooks](observer-hooks.md) remain available to plugins. A user-installed plugin or
an explicitly configured Relay exporter has its own behavior; removing the built-in collector
does not disable those integrations. Relay exporter configuration can come from discovered
user/system configuration or `HERMES_NEMO_RELAY_PLUGINS_TOML`.

## Compaction marks

Compression keeps its local attempt logs, cancellation reasons, and `post_compaction` plugin
hooks. Prepared summaries still use the same validation, slot limits, and cancellation rules.
The former shared-metrics counters for compaction and prepared summaries have been removed.

## Verification

Meu privacy tests exercise migration of old opt-in settings, persistent configuration,
plugin lifecycle dispatch without network access, and absence of collector entry points.
The DeepSeek regression test uses the actual SDK with a local mock transport for a tool-call
round trip. It verifies the provider request path without spending API credit.
