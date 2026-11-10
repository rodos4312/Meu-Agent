# Personal project handoff (pending, no distribution)

Windows and autonomous Android keep local project replicas. A project has one
durable execution owner. Chat observation stays independent and may remain live
on every device. This is a deliberate handoff for a person changing devices,
not concurrent distributed editing or migration of a running process.

## User flow

1. Windows Settings → Gateways: choose the conversation and its separate project
   folder. Android Sync → Projects can also register an existing local project
   subfolder and its conversation.
2. Finish the active turn. On Android choose Continue on phone or Hand to PC.
3. Settle the existing visible-history exchange, transfer the bounded project
   snapshot, verify every file, surrender the previous device's execution owner,
   then activate the verified replica. Wait for the explicit ready message.
4. The new owner can execute without the previous PC/runtime being available.
   The other device stays readable but refuses execution, across restart and
   network loss, until a completed reverse handoff.

Windows can request Continue on PC. The paired phone sees the durable request
on its normal sync cycle and hands the project back once its work is quiet.
The phone application/runtime must be reachable for that handoff; a suspended
or powered-off phone cannot upload unsent work. The PC remains fenced while it
waits. A transfer can be cancelled before source surrender, never by claiming
that a missing network reply means the other executor has stopped.

The existing TLS certificate pin, private-network restriction, revocable pairing,
profile and personal-space checks remain authoritative. The remote peer cannot
register arbitrary PC directories: new phone-origin projects land under the
already selected transfer/personal folder. Absolute local roots never cross the
pairing transport. A native owner selects PC roots, not a browser page.

## File and execution contract

- Portable relative paths, case collisions, links/reparse points and hardlinks
  are checked. Each file carries length, SHA-256 and its executable intent.
- Limit: 4,000 files, 32 MiB per file, 128 MiB total; chunks are 192 KiB. Rejected
  or oversized projects stay on the current owner. No extra build dependencies.
- Known credentials, VCS metadata, caches and generated dependency/build trees
  are excluded. Device-local excluded files remain local on return. Source and
  destination snapshots are verified independently of modification timestamps.
- Files transfer into an inactive sibling staging directory. Activation renames
  the old directory to a retained backup and publishes the validated tree.
  Deletions propagate through the complete snapshot. External edits on an
  inactive replica cause a refusal rather than silent overwrite.
- Registration, offer, release and activation are serialized by the existing
  profile SQLite writer. Active, queued, uncertain, compressed and delegated
  work prevents surrender. Admissions and queued claims check project ownership
  inside their own write transaction. Other chats in that project cannot start
  another worker. The local execution policy resolves the selected local root.
- An offered project is temporarily fenced. Source release is idempotent and
  commits before the grant is returned. There is no timeout-based takeover.
  Android journals the transfer and grant before activation. An interruption
  can be retried after reopening; if the grant is already saved, activation does
  not need the source. If the release response was lost, the source is needed
  again to retrieve the same receipt. Previous data is never deleted to recover.

## Explicit limits

Both devices must be reachable to hand off unsent changes. A powered-off PC
cannot provide files that were never copied. Windows-specific tools/processes
do not become Android-compatible by copying their source. Background processes
and OS environments are not transferred; the receiving engine must inspect the
project and use its own tools. Retained backups require future quota/cleanup UI;
this pending batch deliberately does not automatically delete user data.

Automated source/transport/UI/embedded-runtime checks and physical device
acceptance must be reported separately. No release request or version bump is
part of this batch.
