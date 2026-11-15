import { compactNumber } from '@hermes/shared'

import type { SessionInfo } from '@/hermes'
import type { SidebarRowMeta } from '@/store/layout'
import { sessionCostUsd } from '@/store/sidebar-archive'

/** Tokens and cost shown after a row's title, per the Show menu. */
export function sessionRowFigures(session: SessionInfo, rowMeta: readonly SidebarRowMeta[]): string[] {
  const totalTokens = session.input_tokens + session.output_tokens
  const cost = sessionCostUsd(session)

  return [
    rowMeta.includes('tokens') && totalTokens > 0 ? compactNumber(totalTokens) : null,
    // Sub-cent spend rounds to "$0.00", which reads as a bug rather than as a
    // cheap session — below a cent the row says nothing at all.
    rowMeta.includes('cost') && cost >= 0.01 ? `$${cost.toFixed(2)}` : null
  ].filter(Boolean) as string[]
}
