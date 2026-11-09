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

## Locked installs and shared-chat approvals

Lock validation first checks the existing dependency metadata offline. A valid
lock no longer needs to download an optional direct-URL wheel just to check its
metadata. Stale locks still undergo the normal check, and installation hashes
and dependency verification remain enforced.

Shared messaging approvals can optionally be restricted with
`approvals.approvers: []` (requester and scoped administrators) or an explicit
list of approver IDs. The existing default, `["*"]`, is unchanged; upgrading
does not change the owner's approval settings or add approval prompts. Native
buttons bind the actor and the exact pending request, so an expired card cannot
approve a newer command. Old cards without a request ID require the existing
typed `/approve` command. PC host approval surfaces retain their existing scope.
This concerns shared messaging groups, not PC-phone conversation sync.

Adapted from the upstream Hermes
[offline lock fix](https://github.com/NousResearch/hermes-agent/commit/109fd8161a509db5a00942152ba48882e446e8b0)
and [requester-bound approvals](https://github.com/NousResearch/hermes-agent/commit/466591fe65d0257c96083df16fcd39636032304c),
using Meu's existing approval resolver and native adapter contracts. No Nous
service or telemetry integration is added.

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

Local regression evidence for this candidate includes 206 passing approval
tests and four real uv lock-check tests. The full PM build-operations suite is
also required on Linux; one existing Windows symlink fixture requires a host
privilege unavailable on the local development machine. The focused Windows
lock tests run without that privilege. Release gates remain mandatory.

The owner reported a missing Auto choice in autonomous Android 9680 new-chat
catalogs. A separate Android source correction passed 39 Flutter tests; it is
not installed by this Windows update. The multi-phone trial can still use
explicit models. Android Auto acceptance awaits the corrected Android APK.
