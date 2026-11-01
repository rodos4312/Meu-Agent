import { render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { SharedMetricsConsentDialog } from './consent-dialog'

it('never prompts or requests consent for fresh or switched profiles', () => {
  const requestGateway = vi.fn()

  const { container, rerender } = render(
    <SharedMetricsConsentDialog enabled profile="default" requestGateway={requestGateway} />
  )

  rerender(<SharedMetricsConsentDialog enabled profile="work" requestGateway={requestGateway} />)
  expect(container.childElementCount).toBe(0)
  expect(requestGateway).not.toHaveBeenCalled()
})
