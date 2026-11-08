# Shared transfer folder browsing

Source implementation after the private Android 9678 installer correction.
The published 9678 APK is unchanged. A matching Windows backend and Android
client must be included in a later grouped distribution before phone acceptance.

## User flow

Windows selects one shared root in Settings → Gateways → This window. Android
opens PC file transfers, enters a project subfolder and sends a file to the
folder currently shown. Parent and Shared folder controls return upward.
Refresh reloads the current folder. Downloads use Android's save picker and
retain only the original filename. Folder creation, deletion, whole-folder
uploads and automatic directory synchronization are outside this change.

Files with the same name can exist in separate project subfolders. Existing
files in the selected destination are never overwritten. The 256 MiB per-file
streaming limit, cancellation, existing credentials and PC-online requirement
are retained. Browsing does not transfer agent execution or project state.
Subfolders organize the shared tree; they do not introduce private accounts or
per-phone access control. Separate device grants and permissions require their
own design if multiple people use the same PC.

## Transport and filesystem contract

Both the native Dashboard and existing TLS phone-pairing routes accept an
optional root-relative `path`. Listing adds `folders`, `path`, `browse` and
`directory_id`; existing root-level file operations remain compatible.
Nested listing requires the selected root generation. Nested transfers also
require the directory identity returned by listing, so a replaced child cannot
silently become the transfer destination.

Paths are canonical slash-separated relative components. Parent traversal,
absolute/Windows paths, sensitive names, symlinks and reparse-point directories
are refused. POSIX operations use no-follow directory descriptors; Windows
holds directory/ancestor handles without delete sharing for the admitted disk
operation. Upload publication remains exclusive and partial staging is removed
on cancellation or failure. A changed/revoked root refuses further operations.

The Android client disables transfers during navigation and after a failed
listing, retains a route back to the shared root and never reports a requested
folder as open unless the backend confirms it.

## Validation

- Windows canonical runner: 35 cases passed across real profile stores,
  Dashboard streams and the TLS paired-phone transport. Two POSIX-only cases
  were skipped on Windows; the new file is included in Linux and Windows CI.
- Native Windows checks exercise actual NTFS junction refusal and directory
  handle pinning during an upload. Child replacement and grant revocation refuse
  stale requests. Same-named files in different project folders stay separate.
- Android: eight service/widget cases passed. Targeted Flutter analysis reports
  no issues. Tests cover nested paths/identities, navigation, refresh, failure
  recovery, streaming cancellation and legacy root behavior.
- Windows renderer: 12 existing folder-selection/pairing cases passed.
- All 14 canonical staged-source checks passed with zero health advisories.
  Local whole-working-tree scans also saw unrelated ignored build caches; those
  caches are excluded from the staged-source validation and are not published.
- CI dispatch checks: 54 cases passed initially; two existing replay cases hit
  their 30-second limit while the other local scans were running and both passed
  in the focused rerun. No timeout threshold or CI replay guard was weakened.
- Physical Android browsing and saving against a matching installed PC backend
  remain pending for the next grouped distribution.

No installed applications or user-selected folders are changed by source tests.

## Explicitly deferred continuity work

The user requests one unified conversation after Windows/Android sync instead
of two divergent continuations. Design reconnection and concurrent-message
handling without losing messages, resubmitting them twice or replaying imported
tool calls. This was explicitly postponed; this change does not alter history
sync behavior.
