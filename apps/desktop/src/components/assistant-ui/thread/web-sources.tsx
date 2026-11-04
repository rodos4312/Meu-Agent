import { type ThreadMessage, useAuiState } from '@assistant-ui/react'
import { useMemo } from 'react'

import { extractSearchResults, parseMaybeObject, toolCallFailed } from '@/components/assistant-ui/tool/fallback-model'
import { useI18n } from '@/i18n'
import { ExternalLink } from '@/lib/external-link'

interface Page {
  url: string
  title: string
}

type WebActivity = { kind: 'search'; query: string; provider: string; pages: Page[] } | { kind: 'read'; pages: Page[] }

function publicLinks(items: readonly { url?: unknown; title?: unknown }[]): Page[] {
  const pages = new Map<string, Page>()

  for (const item of items) {
    const url = typeof item.url === 'string' ? URL.parse(item.url) : null

    if (!url || (url.protocol !== 'https:' && url.protocol !== 'http:') || url.username || url.password) {
      continue
    }

    pages.set(url.href, {
      url: url.href,
      title: typeof item.title === 'string' && item.title.trim() ? item.title : url.hostname
    })
  }

  return [...pages.values()]
}

const activityCache = new WeakMap<ThreadMessage['content'], WebActivity[]>()

function readActivity(content: ThreadMessage['content']): WebActivity[] {
  const cached = activityCache.get(content)

  if (cached) {
    return cached
  }

  const activity: WebActivity[] = []

  for (const part of content) {
    if (
      part.type !== 'tool-call' ||
      (part.toolName !== 'web_search' && part.toolName !== 'web_extract') ||
      part.result === undefined ||
      toolCallFailed(part)
    ) {
      continue
    }

    const result = parseMaybeObject(part.result)

    if (part.toolName === 'web_search') {
      const { served_by: provider } = parseMaybeObject(result.data)
      const pages = publicLinks(extractSearchResults(result))
      const query = typeof part.args.query === 'string' ? part.args.query.trim() : ''

      if (result.success === true || pages.length) {
        activity.push({ kind: 'search', query, provider: typeof provider === 'string' ? provider : '', pages })
      }
    } else if (Array.isArray(result.results)) {
      const pages = publicLinks(
        result.results
          .map(parseMaybeObject)
          .filter(
            page => !page.error && !page.blocked_by_policy && typeof page.content === 'string' && page.content.trim()
          )
      )

      if (pages.length) {
        activity.push({ kind: 'read', pages })
      }
    }
  }

  activityCache.set(content, activity)

  return activity
}

function PageLinks({ pages }: { pages: Page[] }) {
  return (
    <ul className="ms-4 list-disc">
      {pages.map(page => (
        <li className="break-words" key={page.url}>
          <ExternalLink href={page.url}>{page.title}</ExternalLink>
        </li>
      ))}
    </ul>
  )
}

export function WebSources({ indices }: { indices: readonly number[] }) {
  const { t } = useI18n()

  const signature = useAuiState(s =>
    JSON.stringify(
      indices.flatMap(index => {
        const message = s.thread.messages[index]

        return message?.role === 'assistant' ? readActivity(message.content) : []
      })
    )
  )

  const activity = useMemo(() => JSON.parse(signature) as WebActivity[], [signature])

  if (!activity.length) {
    return null
  }

  const searches = activity.filter(entry => entry.kind === 'search')
  const pagesRead = publicLinks(activity.filter(entry => entry.kind === 'read').flatMap(entry => entry.pages))

  return (
    <details
      className="border-border/70 text-muted-foreground w-fit max-w-full rounded-md border px-3 py-2 text-xs"
      data-slot="web-sources"
    >
      <summary className="focus-visible:ring-ring cursor-pointer rounded-sm focus-visible:ring-2">
        {t.webSources.title}
      </summary>
      <div className="mt-2 space-y-2">
        {searches.map(({ query, provider, pages }, index) => (
          <div key={index}>
            <p className="text-foreground break-words font-medium">
              {[t.webSources.search, query].filter(Boolean).join(' · ')}
            </p>
            {provider && <p>{t.webSources.provider(provider)}</p>}
            <PageLinks pages={pages} />
          </div>
        ))}
        {pagesRead.length > 0 && (
          <div>
            <p className="text-foreground font-medium">
              {searches.length ? t.webSources.pagesRead : t.webSources.directRead}
            </p>
            <PageLinks pages={pagesRead} />
          </div>
        )}
      </div>
    </details>
  )
}
