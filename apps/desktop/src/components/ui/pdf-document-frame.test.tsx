import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { PdfDocumentFrame } from './pdf-document-frame'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('uses a revocable blob for large valid PDFs and releases it when the document changes or closes', async () => {
  const create = vi.fn().mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second')
  const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const dataUrl = 'data:application/pdf;base64,' + btoa('%PDF-1.4\n' + 'x'.repeat(2_000_000))
  const view = render(<PdfDocumentFrame dataUrl={dataUrl} label="Report" />)
  await waitFor(() => expect(screen.getByTitle('Report').getAttribute('src')).toBe('blob:first'))
  expect(create.mock.calls[0][0].type).toBe('application/pdf')
  view.rerender(<PdfDocumentFrame dataUrl={'data:application/pdf;base64,' + btoa('%PDF-1.4\nSecond')} label="Report" />)
  await waitFor(() => expect(screen.getByTitle('Report').getAttribute('src')).toBe('blob:second'))
  expect(revoke).toHaveBeenCalledWith('blob:first')
  view.unmount()
  expect(revoke).toHaveBeenCalledWith('blob:second')
})

it('does not load HTML or non-PDF bytes into an unsandboxed viewer', async () => {
  const create = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() })

  const view = render(
    <PdfDocumentFrame dataUrl={'data:application/pdf;base64,' + btoa('<html>Bad</html>')} label="Report" />
  )

  await screen.findByRole('alert')
  expect(create).not.toHaveBeenCalled()
  expect(view.container.querySelector('iframe')).toBeNull()
})
