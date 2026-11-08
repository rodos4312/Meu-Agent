# Personal spaces and individually paired devices

Unreleased source change; no APK, installer, version tag or release is produced.

## The simple flow

Choose the shared parent folder on the PC once. In **Users and devices**, enter
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

- This new pairing is for **history sync and file transfers**. It does not give
  a guest arbitrary PC terminal access or claim to sandbox a PC agent by changing
  its working directory. Existing owner-only PC control remains a separate mode.
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
  port are available. Wi-Fi and PC availability are still required here; no
  public relay, external account server or new cloud dependency is added.
- Devices share the existing strict-prefix history sync. Resolving simultaneous
  divergent continuations into one conversation remains explicitly deferred.
- Android stores the optional space name/IDs with its existing protected pairing
  and displays the name in sync and transfers. Old pairing records remain valid.

## Verification before distribution

Local tests exercise real certificate-pinned TLS with separate device secrets,
per-user file contents, session ownership, catalog pagination, revocation,
credential restoration, same-space replacement and legacy compatibility.
Renderer and Flutter tests cover the user/device flow and saved pairing metadata.
Physical multi-phone acceptance and the final grouped build remain pending.
