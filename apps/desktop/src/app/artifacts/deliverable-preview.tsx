import { useEffect, useMemo, useState } from 'react'

import type { ResolvedOwner } from '@/api/client'
import { MarkdownPreview, SourceView } from '@/app/chat/right-rail/preview-file'
import { ZoomableImage } from '@/components/chat/zoomable-image'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PreviewDocumentFrame } from '@/components/ui/preview-document-frame'
import { useI18n } from '@/i18n'
import { downloadTextFile } from '@/lib/download-text'
import { remoteHtmlPreviewDocument } from '@/lib/local-preview'
import { downloadGatewayMediaFile } from '@/lib/media'
import { notifyError } from '@/store/notifications'

import type { ArtifactRecord } from './artifact-utils'
import { type DeliverablePreviewData, readDeliverablePreview } from './preview-data'

function htmlDocument(text: string) {
  const bytes = new TextEncoder().encode(text)

  return (
    remoteHtmlPreviewDocument(
      `data:text/html;base64,${btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(''))}`
    ) || ''
  )
}

export function DeliverablePreview({
  artifact,
  owner,
  onClose,
  onOpenChat
}: {
  artifact: ArtifactRecord
  owner: ResolvedOwner
  onClose: () => void
  onOpenChat: () => void
}) {
  const { t } = useI18n()
  const [data, setData] = useState<DeliverablePreviewData | null>(null)
  const [failed, setFailed] = useState(false)
  const [source, setSource] = useState(false)
  const [retry, setRetry] = useState(0)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let current = true
    setData(null)
    setFailed(false)
    void readDeliverablePreview(artifact, owner).then(
      value => {
        if (current) {
          setData(value)
        }
      },
      () => {
        if (current) {
          setFailed(true)
        }
      }
    )

    return () => {
      current = false
    }
  }, [artifact, owner, retry])

  const document = useMemo(() => (data?.kind === 'html' && !data.truncated ? htmlDocument(data.text) : ''), [data])
  const markdown = data?.language === 'markdown' && !data.binary && !data.truncated

  const download = async () => {
    setSaving(true)

    try {
      if (artifact.inline?.content !== undefined) {
        downloadTextFile(
          artifact.inline.name,
          artifact.inline.content,
          artifact.inline.kind === 'html'
            ? 'text/html'
            : artifact.inline.kind === 'svg'
              ? 'image/svg+xml'
              : 'text/plain'
        )
      } else if (!artifact.inline) {
        await downloadGatewayMediaFile(artifact.value, { owner, sessionId: artifact.sessionId })
      }
    } catch (error) {
      notifyError(error, t.artifacts.openFailed)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      onOpenChange={open => {
        if (!open) {
          onClose()
        }
      }}
      open
    >
      <DialogContent
        bodyClassName="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
        className="flex h-[85dvh] w-[calc(100vw-24px)] max-w-5xl flex-col overflow-hidden"
      >
        <DialogHeader>
          <DialogTitle className="break-words pr-6">{artifact.label}</DialogTitle>
          <DialogDescription className="break-all">
            {artifact.sessionTitle} · {artifact.inline ? t.artifacts.chat : artifact.value}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onOpenChat} size="sm" variant="outline">
            {t.artifacts.chat}
          </Button>
          <Button
            disabled={saving || Boolean(artifact.inline && artifact.inline.content === undefined)}
            onClick={() => void download()}
            size="sm"
            variant="outline"
          >
            {t.fileMenu.download}
          </Button>
          {(data?.kind === 'html' || markdown) && !data?.binary && !data?.truncated && (
            <Button aria-pressed={source} onClick={() => setSource(value => !value)} size="sm" variant="outline">
              {source ? t.preview.renderedPreview : t.preview.source}
            </Button>
          )}
        </div>
        {data?.truncated && (
          <p className="text-sm text-muted-foreground" role="status">
            {t.preview.truncated}
          </p>
        )}
        <div aria-label={t.preview.tab} className="relative min-h-0 flex-1 overflow-hidden rounded-md border">
          {failed ? (
            <div className="p-4" role="alert">
              <p>{t.preview.unavailable}</p>
              <Button onClick={() => setRetry(value => value + 1)}>{t.common.retry}</Button>
            </div>
          ) : !data ? (
            <p className="p-4" role="status">
              {t.preview.loading}
            </p>
          ) : data.binary ? (
            <div className="p-4">
              <p>{t.preview.noInlineTitle}</p>
              <p>{t.preview.noInlineBody(data.mimeType || '')}</p>
            </div>
          ) : data.kind === 'image' ? (
            <ZoomableImage
              alt={artifact.label}
              className="max-h-full max-w-full object-contain"
              src={data.dataUrl || ''}
            />
          ) : data.kind === 'pdf' ? (
            <iframe className="size-full border-0" sandbox="" src={data.dataUrl} title={artifact.label} />
          ) : markdown && !source ? (
            <div className="h-full overflow-auto">
              <MarkdownPreview readOnly text={data.text} />
            </div>
          ) : document && !source ? (
            <PreviewDocumentFrame
              className="size-full border-0 bg-white"
              sandbox=""
              srcDoc={document}
              title={artifact.label}
            />
          ) : (
            <SourceView language={data.language || 'text'} text={data.text} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
