import { beforeEach, expect, it, vi } from 'vitest'

import { hermesApiAs } from '@/api/client'

import type { ArtifactRecord } from './artifact-utils'
import { readDeliverablePreview } from './preview-data'

vi.mock('@/api/client', () => ({ hermesApiAs: vi.fn() }))
const owner = { connectionId: 'remote-one', profile: 'writer' }

const file = (value: string): ArtifactRecord => ({
  id: value,
  kind: 'file',
  value,
  href: '',
  label: 'File',
  sessionId: 'session one',
  sessionTitle: 'Project',
  timestamp: 1
})

beforeEach(() => vi.resetAllMocks())

it.each([
  [String.raw`C:\My project\report.txt`, String.raw`C:\My project\report.txt`],
  ['file:///C:/My%20project/report.txt', String.raw`C:\My project\report.txt`],
  ['file://server/share/report.txt', String.raw`\\server\share\report.txt`],
  ['./report.txt', './report.txt']
])('reads %s from its captured gateway/profile/session', async (value, path) => {
  vi.mocked(hermesApiAs).mockResolvedValue({ path, text: 'Contents', truncated: true })
  expect(await readDeliverablePreview(file(value), owner)).toMatchObject({
    text: 'Contents',
    truncated: true,
    kind: 'text'
  })
  const [actualOwner, request] = vi.mocked(hermesApiAs).mock.calls[0]
  expect(actualOwner).toEqual(owner)
  const url = new URL(request.path, 'https://fixture.invalid')
  expect(url.pathname).toBe('/api/fs/read-text')
  expect(url.searchParams.get('path')).toBe(path)
  expect(url.searchParams.get('session_id')).toBe('session one')
})

it('uses the authenticated image reader and rejects non-image payloads', async () => {
  vi.mocked(hermesApiAs).mockResolvedValue('https://unexpected.example/file')
  await expect(readDeliverablePreview(file('/report.png'), owner)).rejects.toThrow('invalid_preview_data')
  vi.mocked(hermesApiAs).mockResolvedValue({ dataUrl: 'data:image/png;base64,YQ==' })
  expect(await readDeliverablePreview(file('/report.png'), owner)).toMatchObject({
    kind: 'image',
    dataUrl: 'data:image/png;base64,YQ=='
  })
})

it('previews generated Unicode documents without a disk or network read, and keeps oversize entries explicit', async () => {
  const generated = {
    ...file('report.html'),
    inline: {
      kind: 'html' as const,
      title: 'Report',
      language: 'html',
      name: 'report.html',
      hash: '1',
      content: '<html>Ελληνικά</html>'
    }
  }

  expect(await readDeliverablePreview(generated, owner)).toMatchObject({ kind: 'html', text: '<html>Ελληνικά</html>' })
  await expect(
    readDeliverablePreview({ ...generated, inline: { ...generated.inline, content: undefined } }, owner)
  ).rejects.toThrow('inline_preview_limit')
  expect(hermesApiAs).not.toHaveBeenCalled()
})
