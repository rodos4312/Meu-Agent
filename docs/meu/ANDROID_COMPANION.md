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

Use a dedicated Meu test profile with an [enabled API server](../../website/docs/user-guide/features/api-server.md)
behind HTTPS with a certificate trusted by Android. Enter the HTTPS origin and
the gateway access key in the app. The key is held in memory for the connection.
Each connection opens a new API-owned conversation. While that conversation is
open, the app can resume a pending request after a connection error. Confirm
that an interrupted send returns one reply and creates one run. Test with a
Greek message and an incorrect access key before using real data.

## What the existing backend can supply

| Phone action | Existing source and adapter work |
| --- | --- |
| Open a project and chat | Use `projects.list` and `session.resume`. Return only projects and conversations available to the paired profile. Keep desktop paths out of the phone-facing project list. |
| Send a message and resume after a disconnect | Use canonical `prompt.submit` and its submission ID. Retain the ID across retries, reconcile with the admission receipt, and resume from the authoritative session snapshot. |
| Follow helpers | Use `delegation.status` for running helpers and the session's existing events and history for completed work. Filter running entries by the authorized parent session before returning them. |
| Open a deliverable | Resolve a deliverable reference inside its owning session. Reuse the file ticket checks in `hermes_cli/web_routers/files.py` for the transfer. The phone-facing request accepts a deliverable reference instead of a desktop filesystem path. |

## Built-in pairing and the first end-to-end test

Meu for Windows will start and stop a dedicated LAN adapter from its settings.
Meu for Android will scan the pairing QR in the app. The QR contains the local
HTTPS endpoint, a short-lived single-use pairing challenge and the certificate
for that connection. The desktop confirms the new device and binds its
credential to one profile. On Android, protect that credential with a key held
in Android Keystore. Keep model credentials on the desktop. Revoking the device
closes its connection and invalidates its file access. See
[Android network security](https://developer.android.com/privacy-and-security/security-config)
and [Android Keystore](https://developer.android.com/privacy-and-security/keystore).

The Android preview can parse a pasted code and trust its certificate for
that connection while retaining HTTPS hostname checks. Its test format is
`meu1.<origin>.<gateway-key>.<certificate>` with separate unpadded base64url
fields for the HTTPS origin, test key and DER leaf certificate. This direct-key
format is for testing the Android transport. Desktop provisioning, one-time
challenge exchange, in-app QR scanning and device revocation remain to be built
before offering built-in pairing to users.

The pairing implementation pairs one Android phone, opens one synthetic
project, and sends one text message through the same backend as the desktop.
Disconnect during the response, then reconnect. Verify that both clients show
one submitted message and the same completed reply. Try a second profile, a
reused pairing challenge, and a revoked device to verify that access is denied.
Once that slice works, add helper progress and deliverable downloads. Test that
a download from a different session is refused.

The catalog's `hermes-mobile` community adapter is a reference for mobile event
shapes. Its catalog entry describes a plain WebSocket listener with broader
chat and approval privileges. The Meu client needs its own transport and
authorization checks before it can share a desktop profile on a LAN.
