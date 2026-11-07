import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { ArtifactRecord } from './artifact-utils'
import { DeliverablePreview } from './deliverable-preview'
import { type DeliverablePreviewData, readDeliverablePreview } from './preview-data'

vi.mock('./preview-data', () => ({ readDeliverablePreview: vi.fn() }))
vi.mock('@/app/chat/right-rail/preview-file', () => ({ SourceView: ({ text }: { text: string }) => <pre>{text}</pre> }))
vi.mock('@/components/ui/preview-document-frame', () => ({
  PreviewDocumentFrame: (props: React.IframeHTMLAttributes<HTMLIFrameElement>) => <iframe {...props} />
}))

const artifact: ArtifactRecord = {
  id: 'one',
  value: '/report.html',
  label: 'Report',
  href: '',
  kind: 'file',
  sessionId: 'one',
  sessionTitle: 'Birthday',
  timestamp: 1
}

const owner = { connectionId: 'first', profile: 'writer' }
const props = { artifact, owner, onClose: vi.fn(), onOpenChat: vi.fn() }
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

it('renders a document in an isolated frame without active content or external loads and keeps source available', async () => {
  vi.mocked(readDeliverablePreview).mockResolvedValue({
    path: '/report.html',
    kind: 'html',
    text: '<!doctype html><html><body><h1>Birthday card</h1><script>window.open("https://evil.invalid")</script><img src="https://evil.invalid/tracker"><a href="https://evil.invalid">link</a></body></html>'
  })
  render(<DeliverablePreview {...props} />)
  const frame = await screen.findByTitle('Report')
  expect(frame.getAttribute('sandbox')).toBe('')
  const document = frame.getAttribute('srcdoc')!
  expect(document).toContain('Birthday card')
  expect(document).toContain("default-src 'none'")
  expect(document).not.toContain('<script>')
  expect(document).not.toContain('href="https://evil.invalid"')
  fireEvent.click(screen.getByRole('button', { name: 'SOURCE' }))
  await screen.findByText(/<!doctype html>/)
})

it('does not display an old file when an earlier read settles after switching documents', async () => {
  let finish!: (data: DeliverablePreviewData) => void
  vi.mocked(readDeliverablePreview).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const view = render(<DeliverablePreview {...props} />)
  vi.mocked(readDeliverablePreview).mockResolvedValue({ path: '/new.txt', kind: 'text', text: 'New owner content' })
  view.rerender(
    <DeliverablePreview
      {...props}
      artifact={{ ...artifact, id: 'two', value: '/new.txt' }}
      owner={{ connectionId: 'second', profile: 'reader' }}
    />
  )
  await screen.findByText('New owner content')
  await act(async () => finish({ path: '/old.txt', kind: 'text', text: 'Old private content' }))
  expect(screen.queryByText('Old private content')).toBeNull()
  expect(readDeliverablePreview).toHaveBeenLastCalledWith(expect.objectContaining({ value: '/new.txt' }), {
    connectionId: 'second',
    profile: 'reader'
  })
})

it('makes a failed read retryable and distinguishes a truncated preview from a full file', async () => {
  vi.mocked(readDeliverablePreview)
    .mockRejectedValueOnce(new Error('missing'))
    .mockResolvedValue({ path: '/report.html', kind: 'html', text: '<p>Partial contents</p>', truncated: true })
  render(<DeliverablePreview {...props} />)
  const alert = await screen.findByRole('alert')
  fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
  await screen.findByText('<p>Partial contents</p>')
  expect(screen.getByRole('status').textContent).toMatch(/512/)
  expect(screen.queryByTitle('Report')).toBeNull()
})
