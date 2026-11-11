/**
 * Meu Coding — the desktop surface of the Coding Engine: a `/coding` page, a sidebar entry and
 * a palette command. Pure SDK consumer: it talks to the backend's `coding.*` JSON-RPC methods
 * through `host.request`; approval integrity, execution and commits live in the backend.
 */

import {
  type HermesPlugin,
  host,
  PALETTE_AREA,
  type PaletteContribution,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'

import { CodingPage } from './page'

const PATH = '/coding'

const plugin: HermesPlugin = {
  id: 'meu-coding',
  name: 'Coding',
  description: 'Plan, approve, run in an isolated worktree, review the actual diff, keep or commit locally.',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PATH } satisfies RouteContribution, render: () => <CodingPage /> },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        order: 40,
        data: { codicon: 'code', label: 'Coding', path: PATH } satisfies SidebarNavContribution
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'meu-coding.open',
          keywords: ['coding', 'code', 'approve', 'diff', 'worktree'],
          label: 'Open Coding tasks',
          run: () => host.navigate(PATH)
        } satisfies PaletteContribution
      }
    ])
  }
}

export default plugin
