import { type ThreadMessage } from '@assistant-ui/react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $activeSessionId } from '@/store/session'

import { stubThreadEnvironment, stubThreadViewportSize, ThreadRuntime, userMessage } from '../test-utils'
import { Thread } from '../thread'

// The image card, delegate list and delivery notice decide pending-ness from
// `result === undefined`; a call sealed without a result must not stay live.

stubThreadEnvironment()
stubThreadViewportSize()

const createdAt = new Date('2026-09-11T12:00:00Z')
const sealedAt = createdAt.getTime() / 1000 + 5

function sealedMessage(
  toolName: string,
  args: Record<string, unknown>,
  extra: Record<string, unknown> = {}
): Extract<ThreadMessage, { role: 'assistant' }> {
  return {
    id: `assistant-sealed-${toolName}`,
    role: 'assistant',
    content: [
      {
        type: 'tool-call',
        toolCallId: `${toolName}-1`,
        toolName,
        args,
        argsText: JSON.stringify(args),
        completedAt: sealedAt,
        ...extra
      }
    ],
    status: { type: 'complete', reason: 'stop' },
    createdAt,
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: {}
    }
  } as unknown as Extract<ThreadMessage, { role: 'assistant' }>
}

const Harness = ({ message }: { message: ThreadMessage }) => (
  <ThreadRuntime messages={[message]}>
    <Thread />
  </ThreadRuntime>
)

afterEach(() => {
  cleanup()
  $activeSessionId.set(null)
})

describe('tool parts sealed without a result', () => {
  it('renders a sealed delegate_task as the generic row, not a running task list', async () => {
    $activeSessionId.set('sess-1')
    const { container } = render(<Harness message={sealedMessage('delegate_task', { tasks: [{ goal: 'inspect' }] })} />)

    expect(await screen.findByText('Result unavailable')).toBeTruthy()
    expect(container.querySelector('[data-delegate-card]')).toBeNull()
    expect(screen.queryByLabelText('Running')).toBeNull()
  })

  it('renders a sealed image_generate as the generic row, not a rendering placeholder', async () => {
    const { container } = render(<Harness message={sealedMessage('image_generate', { prompt: 'a cat' })} />)

    expect(await screen.findByText('Result unavailable')).toBeTruthy()
    expect(container.querySelector('[data-slot="aui_generated-image"]')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('renders a sealed delivery terminal call as the generic row, not a pending notice', async () => {
    const command = 'hermes -p turqoise chat --in ~ -c "Bot Chat" -Q -q "Message from 🤖 Hermes (@hermes): hi"'
    const { container } = render(<Harness message={sealedMessage('terminal', { command })} />)

    expect(await screen.findByText('Result unavailable')).toBeTruthy()
    expect(container.querySelector('[data-slot="aui_agent-delivery-notice"]')).toBeNull()
  })

  it('renders a call the user interrupted as Interrupted, not as a lost result', async () => {
    render(<Harness message={sealedMessage('terminal', { command: 'ls' }, { interrupted: true })} />)

    expect(await screen.findByText('Interrupted')).toBeTruthy()
    expect(screen.queryByText('Result unavailable')).toBeNull()
  })
})

it('opens the saved project directory from the coordinator result without assistant text', async () => {
  const root = 'C:/Users/Tester/Meu Tasks #1'
  const folderUrl = 'file:///C:/Users/Tester/Meu%20Tasks%20%231'
  const openDir = vi.fn(async () => ({ ok: true }))
  const previousDesktop = window.hermesDesktop
  window.hermesDesktop = {
    ...previousDesktop,
    normalizePreviewTarget: vi.fn(async () => ({
      kind: 'file',
      label: 'Meu Tasks #1',
      path: root,
      previewKind: 'directory',
      source: folderUrl,
      url: folderUrl
    })),
    openDir
  } as typeof window.hermesDesktop

  try {
    render(
      <Harness
        message={sealedMessage(
          'coordinate_project',
          { action: 'status', project: 'demo' },
          {
            result: JSON.stringify({ project: 'demo', root, project_folder_url: folderUrl })
          }
        )}
      />
    )

    expect(await screen.findByText(root)).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: 'Open containing folder' }))
    await waitFor(() => expect(openDir).toHaveBeenCalledWith(root))
  } finally {
    window.hermesDesktop = previousDesktop
  }
})

it('keeps one expandable project card with the latest attempt, model and checks', async () => {
  const task = { goal: 'Fix the import', acceptance: 'Import duplicates and retain one record.' }

  const snapshot = (action: string, row: object, toolCallId: string) =>
    sealedMessage(
      'coordinate_project',
      { action, project: 'demo' },
      {
        toolCallId,
        result: JSON.stringify({ project: 'demo', tasks: { import: { task, ...row } } })
      }
    )

  const started = snapshot('create', { state: 'pending', attempt: 0 }, 'create')

  const checked = snapshot(
    'verify',
    {
      state: 'verified',
      attempt: 2,
      result: { model: 'legacy-model', route: { provider: 'openai-codex', model: 'gpt-6.1-sol' } },
      repair: { check: 'Keep exactly one record with ID constructor.' }
    },
    'verify'
  )

  const running = sealedMessage(
    'coordinate_project',
    { action: 'run', project: 'demo' },
    {
      completedAt: undefined
    }
  )

  const { container, rerender } = render(
    <Harness message={{ ...started, status: { type: 'running' }, content: [...started.content, ...running.content] }} />
  )

  expect(await screen.findByText('Helpers working')).toBeTruthy()
  const cards = container.querySelectorAll<HTMLDetailsElement>('[data-slot="project-progress"] details')
  expect(cards).toHaveLength(1)
  expect(cards[0].open).toBe(false)
  fireEvent.click(screen.getByText('demo'))
  expect(cards[0].open).toBe(true)

  rerender(<Harness message={{ ...started, content: [...started.content, ...checked.content] }} />)

  expect(await screen.findByText('1/1 verified')).toBeTruthy()
  expect(screen.queryByText('0/1 verified')).toBeNull()
  expect(screen.queryByText('Helpers working')).toBeNull()
  expect(container.querySelector('[data-slot="project-progress"] details')).toBe(cards[0])
  expect(cards[0].open).toBe(true)
  expect(screen.getByText('Attempt 2')).toBeTruthy()
  expect(screen.getByText('ChatGPT or Codex Subscription · gpt-6.1-sol')).toBeTruthy()
  expect(screen.queryByText('legacy-model')).toBeNull()
  expect(screen.getByText(task.acceptance)).toBeTruthy()
  expect(screen.getByText('Keep exactly one record with ID constructor.')).toBeTruthy()
})

it('shows the serving search provider and separates discovered from read pages', async () => {
  const search = sealedMessage(
    'web_search',
    { query: 'καιρός Αλιβέρι' },
    {
      result: {
        success: true,
        data: {
          served_by: 'parallel',
          rescued_from: 'exa',
          web: [
            { title: 'Candidate forecast', url: 'https://example.org/forecast' },
            { title: 'Unsafe scheme', url: 'javascript:alert(1)' }
          ]
        }
      }
    }
  )

  const extract = sealedMessage(
    'web_extract',
    { urls: ['https://wttr.in/Aliveri'] },
    {
      result: JSON.stringify({
        results: [
          { title: 'Aliveri forecast', url: 'https://wttr.in/Aliveri', content: 'Cloudy' },
          { title: 'Unreadable page', url: 'https://example.org/blocked', error: 'blocked' }
        ]
      })
    }
  )

  render(
    <ThreadRuntime
      messages={[
        userMessage('user-forecast', 'Τι καιρό θα κάνει;'),
        search,
        { ...extract, content: [...extract.content, { type: 'text', text: 'Cloudy tomorrow.' }] }
      ]}
    >
      <Thread />
    </ThreadRuntime>
  )

  const summary = await screen.findByText('How the information was found')
  expect(summary.closest('details')?.open).toBe(false)
  fireEvent.click(summary)
  expect(screen.getByText('Web search · καιρός Αλιβέρι')).toBeTruthy()
  expect(screen.getByText('Provider: parallel')).toBeTruthy()
  expect(screen.getByText('Pages read')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Candidate forecast' }).getAttribute('href')).toBe(
    'https://example.org/forecast'
  )
  expect(screen.getByRole('link', { name: 'Aliveri forecast' }).getAttribute('href')).toBe('https://wttr.in/Aliveri')
  expect(screen.queryByRole('link', { name: 'Unsafe scheme' })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Unreadable page' })).toBeNull()
})

it('shows a direct page read without inventing a search or provider', async () => {
  render(
    <Harness
      message={sealedMessage(
        'web_extract',
        { urls: ['https://wttr.in/Aliveri'] },
        {
          result: { results: [{ url: 'https://wttr.in/Aliveri', title: 'Forecast', content: 'Cloudy' }] }
        }
      )}
    />
  )

  fireEvent.click(await screen.findByText('How the information was found'))
  expect(screen.getByText('Read directly')).toBeTruthy()
  expect(screen.queryByText(/Provider:/)).toBeNull()
})
