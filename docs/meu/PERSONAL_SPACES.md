# Personal spaces and individually paired devices

First introduced in Windows dev.27. The dev.28 / Android 9684 batch unifies
device enrolment, legacy-owner migration and shared live conversation access.
See [device management](../meu-device-management.md) for migration details.
Physical multi-phone acceptance remains separate from source and CI checks.

## The simple flow

Choose the shared parent folder on the PC once. In **Devices and sharing**, enter
one **Name / nickname**, optionally label the device, and show its QR. For example,
choosing `Downloads/kinito` and entering `Λάζαρος` creates `Downloads/kinito/Λάζαρος`
automatically. Name and nickname are the same field. The folder uses that name,
not a random identifier. Internal IDs remain stable for authorization.

For a second or replacement device, select the existing person. Each device has
its own one-use QR, pinned certificate, persistent credential and disconnect
button. Revoking one device keeps that person's folder and history, and leaves
the other devices connected. A copied old QR cannot enrol a second device.

The native PC owner manages all spaces and continues to see their files and
imported conversations. A personal pairing exposes only its named subtree and
conversations atomically assigned to that space. Neither a guessed session ID
nor a different person's root token grants access. Legacy owner pairings are
preserved and retain their previous explicit scope.

## Scope and limits

- Pairing supports history sync, file transfers and scoped live conversations.
  PC owner devices must be explicitly selected; other users retain their named
  folder and conversation scope. Agent tools follow the PC profile's policy;
  changing a working directory is not an operating-system sandbox.
- Existing unassigned PC conversations are not silently shared with a new user.
- Names are normalized to Unicode NFC, checked for Windows filename safety, and
  compared without case. Invalid names and existing folders are refused; an
  existing folder is never silently adopted as another person's private space.
- Subfolder browsing and upload/download reuse the existing pinned-directory
  transfer engine. Symlinks, junctions, traversal, stale directory tokens and
  overwrites remain refused. An active upload also observes device revocation.
- Selecting the same original shared parent again keeps the personal folders,
  while invalidating stale transfer tokens. Selecting a different parent does
  not move or expose old personal data: select the original parent to reuse it.
- Pairings restore across gateway restarts when their saved LAN address and
  port are available. New QR enrolment includes available Wi-Fi and Tailscale
  endpoints. The PC must be available for live control/transfers; autonomous
  phone work remains separate. No public relay or account server is added.
- Connected views share one live PC conversation. Genuine divergent offline
  continuations retain both versions and require an explicit continuation
  choice; they are not silently merged or selected using timestamps alone.
- Android stores the optional space name/IDs with its existing protected pairing
  and displays the name in sync and transfers. Old pairing records remain valid.

## Verification before distribution

Local tests exercise real certificate-pinned TLS with separate device secrets,
per-user file contents, session ownership, catalog pagination, revocation,
credential restoration, same-space replacement and legacy compatibility.
Renderer and Flutter tests cover the user/device flow and saved pairing metadata.
Physical multi-phone acceptance and the final grouped build remain pending.
