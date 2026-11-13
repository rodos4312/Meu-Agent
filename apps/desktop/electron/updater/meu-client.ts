import electronUpdater from 'electron-updater'

import signing from '../../meu-release-signing.cjs'
import type { InstallStamp } from '../install-stamp'
import { verifyPinnedArtifact } from './artifact'
import { meuChannelOf, meuChannelPreference, meuRcReleasesUrl, STABLE_CHANNEL } from './meu-channel'
import { ensureMeuRecoveryBaseline, retainMeuInstaller } from './meu-recovery'
import { findMeuRelease, meuReleaseDirectory, validateMeuRelease, type MeuRelease } from './meu-release-feed'
import { verifyMeuSignature } from './meu-signature'
import { MeuWindowsStrategy, type MeuWindowsDeps } from './meu-windows'

interface MeuClientDeps extends Pick<MeuWindowsDeps, 'prepare' | 'teardown' | 'restore' | 'emitProgress'> {
  stamp: Readonly<InstallStamp> | null
  currentVersion: string
  executable: string
  recoveryDirectory: string
  log: (message: string) => void
  /** The saved `updates.json` channel; read at every check so a change applies without restart. */
  channelPreference: () => unknown
}

export async function createMeuWindowsStrategy(deps: MeuClientDeps): Promise<MeuWindowsStrategy> {
  const policy = deps.stamp?.meuUpdates
  const build = policy ? meuChannelOf(policy) : STABLE_CHANNEL
  if (!build) {
    throw new Error('This artifact has an invalid Meu update authority.')
  }
  const publisher = policy?.publisherName ?? null
  const authority = policy?.publicKey ?? publisher
  if (policy && Boolean(policy.publicKey) === Boolean(policy.publisherName)) {
    throw new Error('Meu requires exactly one trusted update identity.')
  }
  if (policy?.publicKey) signing.publicKey(policy.publicKey)
  if (publisher) await verifyMeuSignature(deps.executable, publisher, deps.currentVersion)
  // Only the public stable feed installs automatically; an RC build moves to a newer stable release.
  const verifyInstaller = async (file: string, release: MeuRelease): Promise<void> => {
    validateMeuRelease(release, release.version, authority!, STABLE_CHANNEL)
    await verifyPinnedArtifact(file, { url: '', sha256: release.sha256, size: release.size, format: 'exe' })
    if (publisher) await verifyMeuSignature(file, publisher, release.version)
  }
  return new MeuWindowsStrategy({
    ...deps,
    publisher: authority,
    channel: () => {
      const preference = meuChannelPreference(deps.channelPreference(), build.id)
      return { build: build.id, preference, rcReleasesUrl: meuRcReleasesUrl(preference) }
    },
    findRelease: () => findMeuRelease(deps.currentVersion, authority!, undefined, STABLE_CHANNEL, build.id),
    verifySignature: verifyInstaller,
    retain: async (file, release) => {
      // A stable build keeps its own published installer as the rollback baseline. An RC build was
      // installed manually from a private repository, so there is no baseline to fetch.
      if (policy?.publicKey && build.id === 'stable') {
        await ensureMeuRecoveryBaseline(deps.recoveryDirectory, deps.currentVersion, authority!)
      }
      await retainMeuInstaller(deps.recoveryDirectory, file, release, deps.currentVersion, authority!)
      deps.log(
        `Meu update prepared: ${deps.currentVersion} (${build.id}) -> ${release.version} (stable), ` +
          `source ${release.repository}, build ${release.commit.slice(0, 12)}`
      )
    },
    native: release => {
      let handedOff = false
      let installing = false
      let installError: Error | undefined
      const updater = new electronUpdater.NsisUpdater({
        provider: 'generic',
        url: meuReleaseDirectory(release.version),
        channel: STABLE_CHANNEL.channel
      })
      updater.autoDownload = false
      updater.autoInstallOnAppQuit = false
      updater.autoRunAppAfterInstall = true
      updater.disableWebInstaller = true
      updater.disableDifferentialDownload = true
      updater.allowPrerelease = true
      updater.allowDowngrade = false
      // No per-user staging identifier is sent to the public release host.
      updater.requestHeaders = { 'x-user-staging-id': '' }
      updater.on('download-progress', event =>
        deps.emitProgress({ stage: 'fetch', message: 'Downloading the verified Meu release.', percent: event.percent })
      )
      updater.on('error', error => {
        deps.log(`Meu updater: ${error.message}`)
        if (handedOff) {
          handedOff = false
          // BaseUpdater.install reports immediate refusal through this event,
          // then returns normally. Let the handoff owner await recovery once.
          if (installing) {
            installError = error
            return
          }
          deps.emitProgress({ stage: 'error', message: error.message, percent: null })
          void deps.restore().catch(restoreError => {
            deps.log(`Meu update recovery: ${restoreError.message}`)
            deps.emitProgress({ stage: 'error', message: `${error.message}; ${restoreError.message}`, percent: null })
          })
        }
      })
      // Enforce our verifier even when native verification is unavailable or permissive.
      updater.verifyUpdateCodeSignature = async (_names, file) => {
        await verifyInstaller(file, release)
        return null
      }
      return {
        checkForUpdates: () => updater.checkForUpdates(),
        downloadUpdate: () => updater.downloadUpdate(),
        quitAndInstall: () => {
          handedOff = true
          installing = true
          try {
            // Apply is reached only after the user chooses Update now.
            updater.quitAndInstall(true, true)
            if (installError) throw installError
          } catch (error) {
            handedOff = false
            throw error
          } finally {
            installing = false
          }
        }
      }
    }
  })
}
