import { copyFile, mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { verifyPinnedArtifact } from './artifact'
import { validateMeuRelease, type MeuRelease } from './meu-release-feed'

/** Retain verified installers and provenance; never copy or restore live databases here. */
export async function retainMeuInstaller(
  directory: string,
  file: string,
  release: MeuRelease,
  currentVersion: string
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
    validateMeuRelease(rollback, currentVersion, release.publisherName)
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
