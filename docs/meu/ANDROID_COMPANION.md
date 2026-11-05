# Meu Android companion

The Android preview pairs with a running Meu desktop over HTTPS. It supports
shared text sessions. Existing desktop projects, helper activity and
deliverables are planned. See [STATUS.md](STATUS.md) for release status.

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

For access outside home, select **Connect from outside home** before showing
and scanning the QR code. Keep the PC awake and online. Turn off Android Wi-Fi
and send a message over mobile data to test the connection.

Internet mode needs a deployed Meu relay. A deployment operator can run
`python -m gateway.mobile_relay` with aiohttp on a server behind a public HTTPS
reverse proxy that supports WebSocket upgrades. The proxy forwards the relay
origin to port 8766 on the same server. Set `gateway.mobile_relay_url` to that
HTTPS origin in the desktop profile's `config.yaml`. For a direct TLS listener
use `--host 0.0.0.0 --cert fullchain.pem --key privkey.pem` and the intended
public port. The relay forwards encrypted packets. The device secret comes from
the QR code, so the relay cannot decrypt chat content or device credentials.

After pairing, **New session** creates a normal session in the paired profile.
The phone lists sessions created from Android and opens their recent text
history. The same session appears on Windows and can be continued there.
Android refreshes the open session while the app is in the foreground. Pairing
again restores the session list. The preview lists up to 50 sessions and shows the most recent
40 text messages, with a notice when the mobile display limits the history.

New phone-created sessions use the paired profile's model and its enabled
public web tools. A configured web backend supplies live data. Earlier
phone-created conversations retain the toolset they were created with. The
phone can resume an interrupted request during pairing. An
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

The Windows preview starts and stops its private listener from settings. The QR
contains the HTTPS endpoint, a five-minute single-use challenge and either the
listener certificate or the encryption secret. Android saves the verified
device credential encrypted with Android Keystore and reopens the last
conversation on relaunch. The server binds the connection to the issuing profile
and its phone-created sessions. The pairing lasts one hour on the local network
or twelve hours over the internet. Restarting the backend ends the pairing.
Model credentials stay on the desktop. The preview has no file download or
approval routes. See
[Android network security](https://developer.android.com/privacy-and-security/security-config)
and [Android Keystore](https://developer.android.com/privacy-and-security/keystore).

Backend restart recovery and scoped access to existing projects and deliverables
remain future work.

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
