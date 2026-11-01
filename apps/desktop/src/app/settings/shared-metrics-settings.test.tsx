import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { en } from '@/i18n/en'

import { SharedMetricsSettings } from './shared-metrics-settings'

afterEach(cleanup)

it('explains the fixed privacy policy and cannot enable sharing', () => {
  render(<SharedMetricsSettings />)
  const control = screen.getByRole('switch', { name: en.sharedMetrics.sendLabel })

  expect(control.hasAttribute('disabled')).toBe(true)
  expect(control.getAttribute('aria-checked')).toBe('false')
  fireEvent.click(control)
  expect(control.getAttribute('aria-checked')).toBe('false')
  expect(screen.getByText(en.sharedMetrics.sendDesc)).toBeTruthy()
})
