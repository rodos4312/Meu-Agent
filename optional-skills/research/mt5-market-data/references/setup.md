# Optional native MT5 reader

The worker is independent of Meu's Python environment. Upstream version 1.6.1
uses MCP 1.x, while Meu uses MCP 2.x. The two processes communicate through the
MCP stdio protocol; never downgrade Meu's own SDK.

1. Choose an isolated native Windows Python environment and install the packages
   in `scripts/requirements-native.in`. Resolve and retain a hash-locked dependency
   file for that environment. The Windows SDK is not an Android dependency.
2. Save a dedicated TOML configuration. Use an explicit existing terminal path
   and explicit private audit/idempotency paths. Do not add login credentials:
   the reader attaches to the terminal's existing session.

Example (replace paths with the owner's chosen local locations):

~~~toml
[mt5]
terminal_path = 'C:\MT5\terminal64.exe'

[telemetry]
enabled = false
endpoint = ""

[audit]
path = 'D:\Meu-Market\state\audit.jsonl'

[idempotency]
path = 'D:\Meu-Market\state\idempotency.db'
~~~

3. Run the isolated interpreter with this skill's `scripts/readonly_server.py`,
   passing `--config` and the dedicated configuration path. `--check` connects,
   verifies the terminal and read-tool registry, prints a non-account diagnostic,
   and exits. Omit `--check` for the MCP stdio server.
4. Register that interpreter and arguments as a normal stdio `mcp_servers` entry
   named `meu-mt5-market`. Also set `tools.include` to the thirteen tools in SKILL.md.
   Include `get_ea_summary` and `get_market_structure` in that allowlist when upgrading an older installation.
   This client filter complements the server's own registry and SDK restrictions.
5. Start a new Meu conversation to load the new tools without changing the
   cached toolset of a conversation already in progress.

The wrapper uses upstream conversion logic and read tools, with corrected positions/history handlers. It removes every tool
outside the reviewed read allowlist, including chart screenshots and future
unknown tools. Its SDK adapter additionally refuses order mutation, account login
and Market Watch changes. These restrictions protect the MCP data-only surface;
the Python process is not a sandbox against modified or malicious Python code.

The parent Meu process retains its normal authority and selected LLM provider.
Do not describe this as keeping prompts away from the LLM provider. The worker
does not expose an HTTP listener and requires no broker password or cloud relay.

For remote Android use, connect to the PC's Meu through its existing paired
connection. A standalone phone with the PC switched off cannot read an MT5
terminal running only on that PC.

After upgrading this optional worker, finish current work and restart the actual
background gateway to refresh the MCP process and its input schemas. Closing and
reopening the desktop window alone can leave the older gateway and worker alive.
Use the normal gateway restart action (or `hermes gateway restart --detach`); never
force an active turn to stop just to load these tools. Then refresh MCP in the idle
conversation or open a new one, and verify the thirteen-tool registry.

EA arithmetic lives in `scripts/ea_metrics.py`, a standard-library sibling of
`readonly_server.py`. Market comparisons live in `scripts/market_structure.py`.
Install all three files together in the optional worker directory.
The existing raw history tool remains compatible; EA analysis uses the computed
summary. Invalid/conflicting records or changing exposure refuse a verified result.
