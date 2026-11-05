# Meu release retention

The active `rodos4312/Meu-Agent` repository keeps the current published Meu
release and up to two previous published releases: at most three in total.
This is a release-count policy, not a time limit. Infrequent releases can
therefore stay available for months. It does not require a fixed release schedule.

After a Meu release is published, `meu-release-retention.yml` verifies the
retained releases' signed manifests, installer sizes and GitHub SHA-256 digests.
Only after those checks pass does it remove older releases and their download
assets. An incomplete or invalid new publication stops cleanup. Draft releases,
Git tags, commits, source history and local backups are preserved. The archived
`Meu-Agent-Legacy` repository is outside this workflow's scope.

Version ordering uses semantic versions, not publication timestamps. Editing
old release notes does not make that release current. A manual workflow run
defaults to a preview without deleting anything.

## Updating an older installation

Automatic updates retain a verified installer for recovery before changing the
installation. If an older version has been removed and no valid local recovery
copy exists, use the [latest Meu installer](https://github.com/rodos4312/Meu-Agent/releases).
Run it over the existing installation and keep your Meu data folder. Downloading
a new installer does not mean resetting your chats, settings, memory or skills.

The next desktop release includes a clear retired-version message and an
**Open download page** action in its update error dialog. Temporary network or
server failures remain retryable errors; they do not imply that an installation
has become too old. Already installed releases gain this interface change only
when a new application version is shipped.

## Upgrade verification

Native Windows upgrade CI selects the newest verified public release lower
than the candidate version. It verifies the manifest signature and installer
hashes before execution, instead of relying permanently on an old baseline
release that retention may later remove.
