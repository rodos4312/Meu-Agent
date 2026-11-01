import { expect, it, vi } from 'vitest'

import { reportStartupLatency } from './report-startup-latency'

it('neither claims nor reports startup latency, including on an older shell', async () => {
  const request = vi.fn()
  const claimStartupLatency = vi.fn().mockResolvedValue(1234)

  await reportStartupLatency({ claimStartupLatency }, request)
  await reportStartupLatency({}, request)
  await reportStartupLatency(undefined, request)
  expect(request).not.toHaveBeenCalled()
  expect(claimStartupLatency).not.toHaveBeenCalled()
})
