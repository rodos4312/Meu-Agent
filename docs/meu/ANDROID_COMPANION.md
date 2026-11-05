# Meu Android companion

The Android chat preview comes before the Windows trial distribution. It
connects to a running Meu API over HTTPS and starts a separate test conversation.
The full companion will pair with a desktop on the same Wi-Fi network and let
the phone open existing projects and conversations, follow helpers and open
deliverables. See [STATUS.md](STATUS.md) for release status.

## Installable chat preview

Download the `Meu-Android-preview` artifact from the successful **Meu Android
preview** run on `dev/meu-foundation`. It contains the APK and its SHA-256
checksum. The app requires Android 8 or newer. To build it locally on Linux,
install a JDK and Android SDK platform 35 with Build Tools 35.0.0, then run
`bash apps/android/build-preview.sh`. Each build uses a separate test signer.
Uninstall an earlier preview before installing a build with a different signer.

Use a Meu Windows development build with the matching backend and connect the
phone and computer to the same private network. In Windows, open **Settings →
Gateways → Connect a phone** and choose **Show pairing code**. On Android, open
**Scan pairing code**, allow camera access and scan the code in Meu. Send a test
message and confirm the response. Choose **Disconnect phone** to close access.

The preview opens a new text-only conversation in the paired profile and uses
that profile's model. Its temporary connection is limited to that conversation.
The phone can resume an interrupted request during the pairing session. An
already configured [HTTPS API server](../../website/docs/user-guide/features/api-server.md)
can still be used through **Enter address manually**.

## What the existing backend can supply

| Phone action | Existing source and adapter work |
| --- | --- |
| Open a project and chat | Use `projects.list` and `session.resume`. Return only projects and conversations available to the paired profile. Keep desktop paths out of the phone-facing project list. |
| Send a message and resume after a disconnect | Use canonical `prompt.submit` and its submission ID. Retain the ID across retries, reconcile with the admission receipt, and resume from the authoritative session snapshot. |
| Follow helpers | Use `delegation.status` for running helpers and the session's existing events and history for completed work. Filter running entries by the authorized parent session before returning them. |
| Open a deliverable | Resolve a deliverable reference inside its owning session. Reuse the file ticket checks in `hermes_cli/web_routers/files.py` for the transfer. The phone-facing request accepts a deliverable reference instead of a desktop filesystem path. |

## Built-in pairing and the first end-to-end test

The Windows preview starts and stops its LAN listener from settings. The QR
contains the local HTTPS endpoint, a five-minute single-use pairing challenge
and the listener's short-lived certificate. The app verifies the TLS identity
and exchanges the challenge for a temporary credential that is kept in memory.
The server binds the connection to the issuing profile for at most one hour.
Model credentials stay on the desktop. The preview has no file download or
approval routes. See
[Android network security](https://developer.android.com/privacy-and-security/security-config)
and [Android Keystore](https://developer.android.com/privacy-and-security/keystore).

For the full companion, add a desktop device confirmation, persistent pairing
with Android Keystore and scoped access to existing projects and deliverables.

The next integration opens one synthetic project on a paired Android phone and
sends one text message through the same backend as the desktop.
Disconnect during the response, then reconnect. Verify that both clients show
one submitted message and the same completed reply. Try a second profile, a
reused pairing challenge, and a revoked device to verify that access is denied.
Once that slice works, add helper progress and deliverable downloads. Test that
a download from a different session is refused.

The catalog's `hermes-mobile` community adapter is a reference for mobile event
shapes. Its catalog entry describes a plain WebSocket listener with broader
chat and approval privileges. The Meu client needs its own transport and
authorization checks before it can share a desktop profile on a LAN.
