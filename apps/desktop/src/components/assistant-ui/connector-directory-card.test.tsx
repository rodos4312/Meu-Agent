import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { type SessionView, SessionViewProvider } from '@/app/chat/session-view'
import { ConnectorDirectoryCard } from '@/components/assistant-ui/connector-directory-card'
import { I18nProvider } from '@/i18n'
import { $connectionRequests } from '@/store/connection-request'
import { setPrimaryGateway, setPrimaryGatewayConnectionId } from '@/store/gateway'
import { _resetSessionOwnerHintsForTests, setSessionOwnerHint } from '@/store/session'

const SESSION_ID = 'session-1'

const REPLIES = new Map<string, object>([
  [
    'mcp.servers.list',
    {
      servers: [
        { name: 'paper', enabled: true },
        { name: 'disabled', enabled: false },
        { name: 'pending', enabled: true }
      ]
    }
  ],
  [
    'mcp.servers.status',
    {
      servers: [
        { name: 'paper', status: 'connected' },
        { name: 'disabled', status: 'connected' },
        { name: 'pending', status: 'connecting' }
      ]
    }
  ]
])

function gateway() {
  const request = vi.fn(async (method: string) => REPLIES.get(method) ?? {})
  setSessionOwnerHint(SESSION_ID, { connectionId: 'connection-1', profile: 'default' })
  // SAFETY: the card and its queries call only `request` on the primary socket.
  setPrimaryGateway({ request } as never)
  setPrimaryGatewayConnectionId('connection-1')

  return request
}

function view(): SessionView {
  return {
    $awaitingResponse: atom(false),
    $busy: atom(false),
    $cwd: atom(''),
    $fast: atom(false),
    $lastVisibleIsUser: atom(false),
    $messages: atom([]),
    $messagesEmpty: atom(false),
    $model: atom(''),
    $provider: atom(''),
    $reasoningEffort: atom(''),
    $reasoningEffortPending: atom(false),
    $reasoningEffortWire: atom(''),
    $runtimeId: atom(SESSION_ID),
    $storedId: atom(SESSION_ID),
    $turnStartedAt: atom(null),
    kind: 'primary'
  }
}

function inChat(children: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider configClient={null} initialLocale="en">
        <MemoryRouter>
          <SessionViewProvider value={view()}>{children}</SessionViewProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  cleanup()
  $connectionRequests.set({})
  setPrimaryGateway(null)
  _resetSessionOwnerHintsForTests({ storage: true })
  vi.clearAllMocks()
})

describe('Independent MCP directory', () => {
  it('reads only the owning gateway MCP methods and reports live enabled servers', async () => {
    const request = gateway()
    const onContinue = vi.fn()
    inChat(<ConnectorDirectoryCard onContinue={onContinue} />)
    await screen.findByText('paper')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onContinue).toHaveBeenCalledWith({ connected: ['paper'], newly_connected: [], suggested: [] })
    expect(new Set(request.mock.calls.map(([method]) => method))).toEqual(
      new Set(['mcp.servers.list', 'mcp.servers.status'])
    )
  })

  it('shows a gateway failure and permits continuing without claiming a connection', async () => {
    const request = gateway()
    request.mockRejectedValue(new Error('MCP service unavailable'))
    const onContinue = vi.fn()
    inChat(<ConnectorDirectoryCard onContinue={onContinue} />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('MCP service unavailable'))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onContinue).toHaveBeenCalledWith({ connected: [], newly_connected: [], suggested: [] })
  })
})
