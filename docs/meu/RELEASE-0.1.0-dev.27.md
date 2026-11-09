# Meu 0.1.0-dev.27

## Named users and multiple phones

The Windows gateway settings now include **Users and devices**. Choose the
shared parent folder once, enter a name/nickname and optionally name the phone.
Meu creates the personal folder automatically, for example
`kinito/Λάζαρος`. Each device gets its own one-use QR and persistent credential.
You can connect another phone to an existing person or disconnect one device
without deleting that person's files or disconnecting their other devices.

Personal pairings expose only their assigned conversation history and file
subtree. The PC owner can see all personal spaces. Existing owner pairings keep
their previous scope: use a new personal QR for additional users rather than
sharing an owner pairing code. Profiles retain separate device registries.

The first physical trial uses Android 9680 and two phones on the PC's local
network. Named personal pairing currently uses LAN; existing owner Tailscale
connections remain separate. Personal pairing grants history sync and file
transfer, not arbitrary remote terminal or PC-agent control. Simultaneous
divergent conversation histories are still reported as conflicts.

## Files, models and skills

Paired clients can browse shared subfolders and upload/download regular files
through the existing transfer service. Directory boundaries, no-overwrite
behavior and individual device revocation remain enforced.

The Coordinator retains ordered requirements and quality reviews, project
progress and selected-provider model scope. Auto routing honors the configured
provider/model pair and preserves explicit manual session choices. The shared
skill catalog instructs the agent to choose relevant skills from the user's
goal and check their prerequisites without requiring a skill name.

Installer changes include checksum-pinned bundled uv support and bounded retry
of transient downloads. Native clients do not build unused dashboard/terminal
renderers. This release retains the existing Meu update key and channel.

## Installation and verification

Install over the existing Meu installation. Keep the data folder: chats,
settings, memory, skills and projects do not require a reset. Existing personal
folders are not silently adopted as another user's space.

The release candidate must pass the existing Windows/Linux gates, package
scans, signed-update-manifest validation, native upgrade/data-preservation and
failed-startup recovery rehearsals before publication. Automated tests include
real certificate-pinned TLS for isolated devices and transfer/history scopes,
plus the desktop user/device controls. Actual two-phone acceptance remains
pending the owner's trial; CI is not a physical-phone test.
