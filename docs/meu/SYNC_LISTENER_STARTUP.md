# Sync listener startup and status

For history-sync pairing, a temporarily unavailable network adapter must not
discard another adapter that successfully bound. The listener tries the selected
private interfaces independently. A new QR code advertises only endpoints which
actually started, and durable pairing stores those endpoints with matching ports.
If no endpoint starts, pairing fails and no QR code is issued. Existing durable
pairings retain their saved endpoints for the existing restoration loop.

The private desktop status includes `listener_count` and `last_contact` for sync
listeners. `last_contact` is the UTC time of successful pairing or a request with
valid pairing authorization. It resets when the listener is recreated; it is not
a durable sync receipt. Unauthenticated requests do not update it. A running
listener and phone contact do not prove that all conversations have synchronized.

## Verification

- Before the fix, simulated failure of either selected adapter aborts pairing,
  including the case where the other adapter already started (two failing cases).
- After the fix, the tests establish TLS pairing through the surviving endpoint,
  verify the QR advertises only that endpoint, and verify clean failure when all
  endpoints fail.
- Existing transfer and durable-pairing restart tests remain in scope.
- Desktop tests distinguish service readiness, no phone contact and last contact.

These checks do not establish the cause of an individual user's connection
failure. Native Windows verification and a phone-to-PC test remain necessary
before claiming that incident is resolved.
