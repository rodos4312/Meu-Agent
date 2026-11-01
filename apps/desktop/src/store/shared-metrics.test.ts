import { expect, it, vi } from 'vitest'

import {
  readSharedMetricsConsent,
  reportPendingUpdateRun,
  saveSharedMetricsConsent,
  sharedMetricsOfferPending,
  sharedMetricsProfileRequester
} from './shared-metrics'

it('keeps an old backend opted out and routes the persisted refusal to the requested profile', async () => {
  const backend = vi.fn(async () => ({ enabled: true, send: true, decided: false }))
  const request = sharedMetricsProfileRequester(backend as never, 'work')
  const consent = await readSharedMetricsConsent(request)

  expect(consent).toMatchObject({ enabled: false, send: false, decided: true })
  expect(sharedMetricsOfferPending(consent)).toBe(false)
  expect(await saveSharedMetricsConsent(request, { enabled: true, send: true })).toMatchObject({ enabled: false, send: false })
  expect(backend).toHaveBeenLastCalledWith('shared_metrics.set', {
    enabled: false, send: false, first_run: false, profile: 'work'
  })
  backend.mockClear()
  await reportPendingUpdateRun(request)
  expect(backend).not.toHaveBeenCalled()
})
