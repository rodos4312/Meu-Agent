import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as HermesApi from '@/hermes'
import { getUsageAnalytics, type SessionInfo } from '@/hermes'
import { $sessions } from '@/store/session'

import { CommandCenterView } from './index'

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof HermesApi>()),
  getActionStatus: vi.fn(() => Promise.resolve({ running: false })),
  getLogs: vi.fn(() => Promise.resolve({ lines: [] })),
  getStatus: vi.fn(() => Promise.resolve({})),
  getUsageAnalytics: vi.fn(() => Promise.resolve({})),
  restartGateway: vi.fn(),
  updateHermes: vi.fn()
}))
vi.mock('@/lib/session-export', () => ({ exportSession: vi.fn() }))
vi.mock('./maintenance', () => ({ MaintenancePanel: () => null }))

afterEach(() => {
  cleanup()
  $sessions.set([])
})

const SESSION = {
  connection_id: 'gw-tailscale',
  ended_at: null,
  id: 'sess-remote',
  input_tokens: 0,
  is_active: false,
  last_active: 1_756_600_000,
  message_count: 3,
  model: null,
  output_tokens: 0,
  profile: 'research',
  started_at: 1_756_500_000,
  title: 'Remote conversation'
} as SessionInfo

it('shows distinct call and token counts for Flash and Pro from local history', async () => {
  vi.mocked(getUsageAnalytics).mockResolvedValueOnce({
    by_model: [
      { model: 'deepseek-v4-flash', input_tokens: 100, output_tokens: 10, api_calls: 1, sessions: 1, estimated_cost: 0 },
      { model: 'deepseek-v4-pro', input_tokens: 200, output_tokens: 20, api_calls: 2, sessions: 1, estimated_cost: 0 }
    ],
    daily: [],
    period_days: 30,
    skills: { summary: { distinct_skills_used: 0, total_skill_actions: 0, total_skill_edits: 0, total_skill_loads: 0 }, top_skills: [] },
    totals: {
      total_actual_cost: 0, total_estimated_cost: 0, total_cache_read: 0, total_reasoning: 0,
      total_input: 300, total_output: 30, total_api_calls: 3, total_sessions: 1
    }
  })
  render(
    <MemoryRouter>
      <CommandCenterView initialSection="usage" onClose={() => {}} onDeleteSession={async () => {}} onOpenSession={() => {}} />
    </MemoryRouter>
  )

  expect((await screen.findByText('deepseek-v4-flash')).closest('li')?.textContent).toContain('API calls 1 · Tokens in/out 100 / 10')
  expect(screen.getByText('deepseek-v4-pro').closest('li')?.textContent).toContain('API calls 2 · Tokens in/out 200 / 20')
})

// Same open-path contract as the cron run rows (#82527): a list row hands its
// owner (connection, profile) to the open call so a remote/other-profile row
// resumes on the backend that owns it, not the ambient one.
describe('Command Center session open carries the row', () => {
  beforeEach(() => {
    $sessions.set([SESSION])
  })

  it('passes the clicked ROW to onOpenSession, not a bare id', async () => {
    const onOpenSession = vi.fn()
    render(
      <MemoryRouter>
        <CommandCenterView
          initialSection="sessions"
          onClose={() => {}}
          onDeleteSession={() => Promise.resolve()}
          onOpenSession={onOpenSession}
        />
      </MemoryRouter>
    )

    const title = await screen.findByText('Remote conversation')
    fireEvent.click(title.closest('button') as HTMLButtonElement)

    expect(onOpenSession).toHaveBeenCalledWith(SESSION.id, SESSION)
  })
})
