import { copyFile, mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { downloadPinnedArtifact, verifyPinnedArtifact } from './artifact'
import { fetchMeuResponse, meuReleaseDirectory, readMeuRelease, validateMeuRelease, type MeuRelease } from './meu-release-feed'

/** Keep a verified current installer even on the first update of an installation. */
export async function ensureMeuRecoveryBaseline(directory: string, version: string, authority: string): Promise<void> {
  await mkdir(directory, { recursive: true })
  try {
    const previous = JSON.parse(await readFile(path.join(directory, 'meu-update-recovery.json'), 'utf8'))
    const cached = [previous.target, previous.rollback].find(release => release?.version === version)
    if (cached) {
      validateMeuRelease(cached, version, authority)
      await verifyPinnedArtifact(path.join(directory, cached.file), {
        url: '', sha256: cached.sha256, size: cached.size, format: 'exe'
      })
      return
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const baseline = await readMeuRelease(version, authority)
  const temporary = await mkdtemp(path.join(directory, 'baseline-'))
  try {
    const file = await downloadPinnedArtifact(temporary, {
      url: meuReleaseDirectory(version) + baseline.file,
      sha256: baseline.sha256, size: baseline.size, format: 'exe'
    }, url => fetchMeuResponse(url, 600_000))
    await retainMeuInstaller(directory, file, baseline, version, authority)
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }
}

/** Retain verified installers and provenance; never copy or restore live databases here. */
export async function retainMeuInstaller(
  directory: string,
  file: string,
  release: MeuRelease,
  currentVersion: string,
  authority: string = release.publisherName
): Promise<void> {
  await mkdir(directory, { recursive: true })
  const destination = path.join(directory, release.file)
  const partial = `${destination}.partial`
  await copyFile(file, partial)
  await verifyPinnedArtifact(partial, { url: '', sha256: release.sha256, size: release.size, format: 'exe' })
  await rename(partial, destination)
  const journal = path.join(directory, 'meu-update-recovery.json')
  let previous: { target?: MeuRelease; rollback?: MeuRelease } | null = null
  try {
    previous = JSON.parse(await readFile(journal, 'utf8'))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const rollback =
    [previous?.target, previous?.rollback].find(candidate => candidate?.version === currentVersion) ?? null
  if (rollback) {
    validateMeuRelease(rollback, currentVersion, authority)
    await verifyPinnedArtifact(path.join(directory, rollback.file), {
      url: '',
      sha256: rollback.sha256,
      size: rollback.size,
      format: 'exe'
    })
  }
  await writeFile(
    journal + '.partial',
    JSON.stringify(
      { schema: 1, fromVersion: currentVersion, target: release, rollback, preparedAt: new Date().toISOString() },
      null,
      2
    ),
    { mode: 0o600 }
  )
  await rename(journal + '.partial', journal)
}
