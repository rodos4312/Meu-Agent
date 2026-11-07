# Unified deliverables and file previews — 2026-11-07

Unreleased development work on `dev/meu-foundation`. Public Windows remains
dev.25; Android remains source build 9673. No installer, APK, tag or update feed
is published by this batch, and the installed Meu is not changed.

## Behavior

- Windows' existing Artifacts page combines delivered files, images, links and
  completed generated HTML/SVG/code documents. It retains the existing recent
  30-session catalog, with search, type tabs and a conversation selector.
- A file opens inside a read-only preview dialog. Download and return to the
  owning chat are separate actions. Text/code, inert formatted Markdown,
  images, SVG and HTML use existing viewers; PDF uses the browser viewer.
  Other binary formats show their metadata and retain Download.
- Every file read/download carries its captured connection, profile and
  session. Changing connection/profile clears the catalog and open preview;
  late results cannot replace the newly selected file. Failed reads offer
  Retry. Truncated source is labelled and is not rendered as a complete HTML
  document. Download remains a separate full-file request.
- Generated blocks reuse chat's artifact detection and filenames. Unfinished
  fences and short snippets are excluded. Cached inline bodies are bounded
  to 512,000 characters each and 2,000,000 total; oversize entries retain their
  metadata and source-chat action, rather than disappearing.
- HTML previews reuse the existing sanitized document/CSP and sandboxed frame.
  Catalog Markdown does not resolve images or local links against another
  foreground gateway. No preview automatically opens an OS application.
- Android's current-session list combines generated documents and delivered
  files, with search, type filters, preview, Save and a separate source-message
  action. Generated versions retain the existing selector/source/export and
  add the existing isolated document viewer.
- Android preview and Save reuse one bounded authenticated download. The new
  flow uses `/api/fs/download` with the owning profile and session, including
  native Windows drive/UNC paths. Explicit assistant `MEDIA:` deliveries now
  join tool deliveries; prose, user examples, fenced examples, traversal,
  private-key paths and arbitrary external download hosts remain excluded.
- Android HTML/SVG reuse the existing isolated WebView policy; Markdown/text
  and images use native viewers. **PDF and other unsupported formats show
  metadata and Save, not rendered document pages.** A failed read can retry.

## Verification

- 61 Windows UI tests passed across the artifact index, generated documents,
  scoped reads/downloads, stale-result handling, HTML/Markdown isolation,
  existing file-save ownership and the welcome mark.
- The old file rail and the new catalog share one PDF frame. It retains the
  existing native Chromium viewer, validates PDF MIME/base64/header, uses a
  blob URL instead of a large data URL, and revokes it on change/close. HTML
  continues to use its separate sandboxed frame; it cannot enter the PDF frame.
- Desktop/Electron/e2e type checks passed; changed Windows sources passed ESLint.
  The local desktop build passed. The obsolete wordmark source assertion was
  replaced by the actual welcome-component identity test; the branding script
  also passed locally. This addresses the previous CI identity failure without
  reverting the new UI.
- Three real Electron tests passed with an isolated backend and temporary data:
  delivered-file/generated-document previews (including frame sizing and no
  scripted external request), navigation/draft retention/responsive layout,
  and project notes surviving an application restart.
- The enhanced deliverables rehearsal also opened a real one-page PDF through
  the native Chromium viewer. Its loaded page was visually inspected; this
  verifies more than assigning an iframe URL.
- 252 focused Android tests passed across 27 suites: the new browser and
  authenticated preview/Save flow, generated-media paths and detection,
  HTML policy/viewers/export, artifact indexing/navigation, projects/files,
  read-only and conflict behavior, session detail, device/auth and identity.
  The current-session floating-surface-to-preview path is also exercised.
- Changed Android code/tests passed static analysis. Light/dark phone-width
  renders were inspected. No model-provider request was used in these tests.
- Windows CI now includes the new preview suites and Electron rehearsal.
  A local pass is not a claim that a later GitHub run has completed.

## Remaining acceptance

No physical Android installation, actual Android WebView engine run, real-device
Save dialog, mobile-data transition, long background run or real Windows reboot
was performed. Existing HTML WebView policy tests use a fake platform. The
Windows PDF checks cover one ordinary page, not encrypted documents, complex
forms or a large-file corpus; external Android PDF apps are not certified by
this batch. Office/ZIP binary formats are download-only. These limits do not
block source development, but remain part of the consolidated release check.

The next roadmap work is Coordinator progress and delivery receipts, followed
by the grouped stability/acceptance checks and one consolidated distribution.
