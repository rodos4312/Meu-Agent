import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { readMeuObservation } from '@/api/meu-observation'

import { MeuObservationView } from './meu-observation'

vi.mock('@/api/meu-observation', () => ({ readMeuObservation: vi.fn() }))
vi.mock('@/components/pane-shell/pane-visibility', () => ({ usePaneVisible: () => true }))

const read = vi.mocked(readMeuObservation)
const progress = (draft: string) => ({ id: 'shared', busy: true, draft, messages: [] })

beforeEach(() => { vi.useFakeTimers(); read.mockReset() })
afterEach(() => { cleanup(); vi.useRealTimers() })

it('paints progress before completion without creating editable transcript messages', async () => {
  read.mockResolvedValueOnce(progress('First progress'))
    .mockResolvedValueOnce(progress('More progress'))
    .mockResolvedValueOnce(null)
  await act(async () => {
    render(<MeuObservationView connectionId="pc" enabled profile="work" sessionId="shared" />)
  })
  expect(screen.getByText('First progress')).toBeTruthy()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(read).toHaveBeenLastCalledWith('shared', 'pc', 'work')
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.getByText('More progress')).toBeTruthy()
  expect(screen.queryByText('First progress')).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.queryByLabelText('Paired device progress')).toBeNull()
})

it('a display outage retains marked progress and recovers without a chat reconnect', async () => {
  read.mockResolvedValueOnce(progress('Existing progress'))
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(progress('Connection recovered'))
  await act(async () => { render(<MeuObservationView enabled sessionId="shared" />) })
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.getByText('Existing progress')).toBeTruthy()
  expect(screen.getByText('Paired device · Waiting for connection')).toBeTruthy()
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.getByText('Connection recovered')).toBeTruthy()
})

it('does not publish an old response into another conversation or a locally running turn', async () => {
  let finish!: (value: ReturnType<typeof progress>) => void
  read.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const view = render(<MeuObservationView enabled key="old" sessionId="shared" />)
  view.rerender(<MeuObservationView enabled={false} key="new" sessionId="another" />)
  await act(async () => { finish(progress('Old private response')) })
  expect(screen.queryByText('Old private response')).toBeNull()
  expect(read).toHaveBeenCalledTimes(1)
})
