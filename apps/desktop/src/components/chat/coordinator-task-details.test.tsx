import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { coordinatorTasks } from '@/lib/coordinator-progress'

import { CoordinatorTaskDetails } from './coordinator-task-details'

afterEach(cleanup)

it('explains acceptance and review evidence while leaving a completed review unverified', () => {
  const [task] = coordinatorTasks({
    progress: [
      {
        id: 'review',
        goal: 'Review imports',
        state: 'needs_review',
        attempt: 2,
        acceptance: 'Exactly one task remains',
        depends_on: ['build'],
        review_of: 'build',
        evidence: 'Fixture executed',
        review: { verdict: 'pass', check: 'Import duplicate', observed: 'One task remained', reviewed_attempt: 1 }
      }
    ]
  })

  render(<CoordinatorTaskDetails task={task} />)
  expect(screen.getByText('Awaiting verification')).toBeTruthy()
  expect(screen.getByText('Exactly one task remains')).toBeTruthy()
  expect(screen.getByText('Review result · Pass reported')).toBeTruthy()
  expect(screen.getByText('One task remained')).toBeTruthy()
  fireEvent.click(screen.getByText('Recorded checks'))
  expect(screen.getByText('Fixture executed')).toBeTruthy()
  expect(screen.queryByText('Verified')).toBeNull()
})
