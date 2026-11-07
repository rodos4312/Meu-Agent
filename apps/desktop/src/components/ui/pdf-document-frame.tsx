import { useEffect, useState } from 'react'

import { useI18n } from '@/i18n'

function dataUrlToBlob(dataUrl: string) {
  const comma = dataUrl.indexOf(',')

  if (comma < 0 || !dataUrl.startsWith('data:')) {
    throw new Error('Invalid PDF data URL')
  }

  const metadata = dataUrl
    .slice(5, comma)
    .split(';')
    .map(part => part.trim().toLowerCase())

  const payload = dataUrl.slice(comma + 1)

  if (metadata[0] !== 'application/pdf' || !metadata.slice(1).includes('base64')) {
    throw new Error('Invalid PDF data URL type')
  }

  let binary: string

  try {
    binary = atob(decodeURIComponent(payload))
  } catch {
    throw new Error('Invalid PDF data URL payload')
  }

  if (!binary.startsWith('%PDF-')) {
    throw new Error('Invalid PDF file header')
  }

  const bytes = new Uint8Array(binary.length)

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }

  return new Blob([bytes], { type: 'application/pdf' })
}

/** Native Chromium PDF viewer: validate the payload and use a revocable blob.
 * PDF plugins cannot render in a sandboxed HTML iframe or large data URL.
 * The HTML preview continues to use its separate sanitized/sandboxed frame. */
export function PdfDocumentFrame({ dataUrl, label }: { dataUrl: string; label: string }) {
  const { t } = useI18n()
  const [state, setState] = useState<{ input: string; url?: string; failed?: boolean } | null>(null)
  useEffect(() => {
    let url: string

    try {
      url = URL.createObjectURL(dataUrlToBlob(dataUrl))
      setState({ input: dataUrl, url })
    } catch {
      setState({ input: dataUrl, failed: true })

      return
    }

    return () => URL.revokeObjectURL(url)
  }, [dataUrl])

  if (state?.input === dataUrl && state.failed) {
    return (
      <p className="p-4" role="alert">
        {t.preview.unavailable}
      </p>
    )
  }

  if (state?.input !== dataUrl || !state.url) {
    return (
      <p className="p-4" role="status">
        {t.preview.loading}
      </p>
    )
  }

  return <iframe aria-label={label} className="h-full w-full border-0 bg-white" src={state.url} title={label} />
}
