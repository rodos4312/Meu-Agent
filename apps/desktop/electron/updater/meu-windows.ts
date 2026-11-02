import type { UpdateCheckResult, UpdateInfo } from 'electron-updater'

import { verifyPinnedArtifact } from './artifact'
import type { UpdaterApplyResultWire, UpdaterStatusWire, UpdaterStrategy } from './index'
import type { MeuRelease } from './meu-release-feed'
import { applyPackagedHandoff } from './packaged-handoff'

export interface MeuWindowsDeps {
  currentVersion: string
  publisher: string | null
  findRelease: () => Promise<MeuRelease | null>
  native: (release: MeuRelease) => {
    checkForUpdates: () => Promise<UpdateCheckResult | null>
    downloadUpdate: () => Promise<string[]>
    quitAndInstall: () => void
  }
  verifySignature: (file: string, version: string) => Promise<void>
  retain: (file: string, release: MeuRelease) => Promise<void>
  prepare: () => Promise<void>
  teardown: () => Promise<void>
  restore: () => Promise<void>
  emitProgress: (event: { stage: string; message: string; percent: number | null }) => void
}

export function verifyMeuNativeFeed(info: UpdateInfo, release: MeuRelease): void {
  const files = info.files
  if (
    info.version !== release.version ||
    !Array.isArray(files) ||
    files.length !== 1 ||
    files[0].url !== release.file ||
    files[0].sha512 !== release.sha512 ||
    files[0].size !== release.size
  ) {
    throw new Error('Native Meu feed does not match the selected release.')
  }
}

/** The existing update UI drives this strategy; no automatic install on quit. */
export class MeuWindowsStrategy implements UpdaterStrategy {
  readonly mechanism = 'electron-updater' as const
  private applying = false

  constructor(private readonly deps: MeuWindowsDeps) {}

  async check(): Promise<UpdaterStatusWire> {
    if (!this.deps.publisher) {
      return {
        supported: false,
        mechanism: this.mechanism,
        reason: 'meu-signing-not-configured',
        message: 'Meu automatic installation is disabled until a signed Meu release is available.',
        fetchedAt: Date.now()
      }
    }
    const release = await this.deps.findRelease()
    return {
      supported: true,
      mechanism: this.mechanism,
      channel: 'meu-preview',
      currentVersion: this.deps.currentVersion,
      updateAvailable: Boolean(release),
      latestTag: release ? `meu-v${release.version}` : null,
      targetSha: release?.commit,
      fetchedAt: Date.now()
    }
  }

  async apply(): Promise<UpdaterApplyResultWire> {
    if (!this.deps.publisher) throw new Error('Meu signing is not configured; no update will be installed.')
    if (this.applying) throw new Error('A Meu update is already in progress.')
    this.applying = true
    try {
      return await applyPackagedHandoff(this.deps, async stop => {
        const release = await this.deps.findRelease()
        if (!release) return { ok: true, mechanism: this.mechanism }
        const native = this.deps.native(release)
        const result = await native.checkForUpdates()
        if (!result?.isUpdateAvailable) throw new Error('Native updater did not admit the selected Meu release.')
        verifyMeuNativeFeed(result.updateInfo, release)
        this.deps.emitProgress({ stage: 'fetch', message: 'Downloading the signed Meu release.', percent: null })
        const files = await native.downloadUpdate()
        if (files.length !== 1) throw new Error('Expected exactly one Meu update installer.')
        const file = files[0]
        await verifyPinnedArtifact(file, { url: '', sha256: release.sha256, size: release.size, format: 'exe' })
        await this.deps.verifySignature(file, release.version)
        await this.deps.retain(file, release)
        this.deps.emitProgress({
          stage: 'prepare',
          message: 'Preparing Meu recovery and checking active work.',
          percent: null
        })
        await this.deps.prepare()
        await stop()
        this.deps.emitProgress({
          stage: 'restart',
          message: 'Restarting Meu to install the verified release.',
          percent: 100
        })
        native.quitAndInstall()
        return { ok: true, mechanism: this.mechanism, handedOff: true }
      })
    } finally {
      this.applying = false
    }
  }
}
