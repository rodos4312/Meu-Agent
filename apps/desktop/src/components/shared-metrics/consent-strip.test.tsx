import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import { SharedMetricsConsentStrip } from './consent-strip'

it('does not offer telemetry consent in Meu', () => {
  const { container } = render(<SharedMetricsConsentStrip />)

  expect(container.childElementCount).toBe(0)
})
