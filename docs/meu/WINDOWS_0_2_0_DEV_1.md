# Meu Windows 0.2.0-dev.1 — small public candidate

The desktop automatically installs or advances its Python core to the exact
revision shipped in its small local source package. No private GitHub login or
token is needed. The package omits preinstalled environments and the offline
wheel cache; first setup needs internet for hash-locked dependencies. Subsequent
updates reuse PM's existing tools, download cache and immutable environments.

Existing conversations, projects, provider settings and device pairings stay in
their existing home, separate from the managed source checkout. Before advancing
an existing core, the ordinary gateway lifecycle refuses active work and the
existing full backup command must succeed. It keeps every prior backup. Dirty,
foreign or divergent checkouts are refused; older installers never downgrade a
newer core. A failed dependency install remains retryable; the prior source
commit and user backup remain available for recovery. No automatic profile
rewind is performed, which could erase work received after the snapshot.

The app contains its renderer and precompiled web/terminal products. Bootstrap
completes the backend without rebuilding Electron/TUI/web frontends on the user's
PC. The web dashboard and the paired Meu Mobile gateway remain available.

The Windows source and standard candidate checks are public in rodos4312/Meu-Agent
on dev/meu-foundation. The usual public preview update channel owns subsequent
desktop updates; the core follows the exact installed app revision automatically.
The former dev.33 reference is frozen in the private archive/dev33 branch. Android
preview source, signers and test packages remain private and unchanged.

GitHub-hosted checks are not a requirement to install Meu. Local build/test outputs
are retained separately from actual GitHub job results; quota-blocked jobs are
never reported as passed. Standard hosted runners on this public source do not
consume private-repository compute allowance.

Validation must include native source installation/upgrade and the actual
installed app's bootstrap, authenticated gateway/renderer and profile-preserving
repair. A candidate build alone is not proof of a user's successful upgrade.
