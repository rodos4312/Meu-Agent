import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { SessionInfo } from '@/hermes'
import { revealPath } from '@/store/projects'

import { CoordinatorWorkspace } from './coordinator-workspace'
import type { SidebarProjectTree } from './workspace-groups'

vi.mock('@/store/projects', () => ({ revealPath: vi.fn() }))
vi.mock('@/store/connections', async () => {
  const { atom } = await import('nanostores')

  return { $activeConnectionId: atom('local') }
})
vi.mock('@/store/file-actions', () => ({ shouldOfferLocalReveal: () => true }))

afterEach(cleanup)

it('shows saved progress and reveals a verified file or opens the linked continuation', () => {
  const resume = vi.fn()
  const refresh = vi.fn()
  const session = { id: 'continued', _lineage_root_id: 'original', connection_id: 'local' } as SessionInfo

  const project: SidebarProjectTree = {
    id: 'workspace',
    label: 'Workspace',
    path: '/work',
    sessionCount: 2,
    repos: [{
      id: 'repo',
      label: 'Repo',
      path: '/work',
      sessionCount: 2,
      groups: [{ id: 'lane', label: 'Main', path: '/work', sessions: [{ id: 'other' } as SessionInfo, session] }]
    }],
    coordinatorPlans: [{
      id: 'plan',
      root: '/work',
      session_id: 'original',
      tasks: [
        { id: 'inspect', goal: 'Inspect', state: 'interrupted', artifacts: [] },
        { id: 'write', goal: 'Write', state: 'verified', provider: 'openai-codex', model: 'gpt-6.1-sol',
          artifacts: [{ name: 'answer.txt', path: '/work/answer.txt' }] }
      ]
    }]
  }

  render(<CoordinatorWorkspace onRefresh={refresh} onResumeSession={resume} project={project} />)
  fireEvent.click(screen.getByText('plan · 1/2 verified'))
  expect(screen.getByText('Interrupted')).toBeTruthy()
  expect(screen.getByText('Verified · ChatGPT or Codex Subscription · gpt-6.1-sol')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  expect(resume).toHaveBeenCalledWith('continued', session)
  fireEvent.click(screen.getByRole('button', { name: 'answer.txt' }))
  expect(revealPath).toHaveBeenCalledWith('/work/answer.txt')
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(refresh).toHaveBeenCalledOnce()
})
