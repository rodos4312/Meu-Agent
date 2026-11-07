# Meu 0.1.0-dev.25

## Phone pairing and sync service

History-sync pairing now keeps a working Ethernet/Wi-Fi listener if Tailscale
cannot start, and keeps a working Tailscale listener if the local interface
cannot start. A new QR code includes only endpoints that actually started.
If neither endpoint starts, no pairing code is issued.

Desktop distinguishes service readiness from the last authenticated contact
with the phone. Contact does not imply that every conversation is up to date.
The contact timestamp resets when the sync service is recreated.

This addresses a reproduced adapter-startup failure. It does not establish the
cause of every reported connection failure; test the corrected installed build
with the phone before considering an individual incident resolved.

## Validation and maintenance

The targeted native Windows sync workflow passed before release preparation,
covering partial adapter failure, TLS pairing and durable pairing restart.
Desktop status/catalog tests and the renderer TypeScript check also passed.
The full Windows installer, upgrade and recovery gates run for this version.

Project-note configuration checks now use the shared config backend. Windows
reserved-name matching uses the equivalent explicit regular-expression flag.

Install over the existing version. Keep the existing Meu data folder; there is
no reason to uninstall first or remove chats, settings, memory or skills.
