# Meu Android companion

The first Android client connects to a running Meu desktop backend on the same
Wi-Fi network. A paired phone can open existing projects and conversations,
send a message, follow its helpers, and open the deliverables. Implementation
follows the desktop release and Coordinator trial in [STATUS.md](STATUS.md).

## What the existing backend can supply

| Phone action | Existing source and adapter work |
| --- | --- |
| Open a project and chat | Use `projects.list` and `session.resume`. Return only projects and conversations available to the paired profile. Keep desktop paths out of the phone-facing project list. |
| Send a message and resume after a disconnect | Use canonical `prompt.submit` and its submission ID. Retain the ID across retries, reconcile with the admission receipt, and resume from the authoritative session snapshot. |
| Follow helpers | Use `delegation.status` for running helpers and the session's existing events and history for completed work. Filter running entries by the authorized parent session before returning them. |
| Open a deliverable | Resolve a deliverable reference inside its owning session. Reuse the file ticket checks in `hermes_cli/web_routers/files.py` for the transfer. The phone-facing request accepts a deliverable reference instead of a desktop filesystem path. |

## Pairing and the first end-to-end test

The desktop opts in to a dedicated LAN adapter with a small versioned API. Its
QR code contains the local endpoint, a short-lived single-use pairing challenge,
and information for verifying the desktop's TLS identity. The desktop confirms
the new device and binds its credential to one profile. On Android, protect that
credential with a key held in Android Keystore. Keep the model credentials on
the desktop. Revoking the device closes its connection and invalidates its file
access. See [Android network security](https://developer.android.com/privacy-and-security/security-config)
and [Android Keystore](https://developer.android.com/privacy-and-security/keystore).

The first implementation slice pairs one Android phone, opens one synthetic
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
