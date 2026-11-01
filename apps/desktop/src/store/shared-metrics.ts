import type { SharedMetricsConsentResult } from '@hermes/shared'
import { atom } from 'nanostores'

import { setDesktopMetricsGate } from './desktop-metrics'

export type SharedMetricsConsent = SharedMetricsConsentResult

/** Legacy callers may still name share; both answers enforce the Meu opt-out. */
export type SharedMetricsChoice = 'off' | 'share'

export const SHARED_METRICS_CHOICES: Record<SharedMetricsChoice, { enabled: boolean; send: boolean }> = {
  share: { enabled: false, send: false },
  off: { enabled: false, send: false }
}

export type SharedMetricsRequester = <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>

/**
 * Name the profile on every consent RPC: an unscoped one resolves to the
 * backend's launch home, so on a shared backend the answer landed in another
 * profile's config.yaml and the focused profile's offer never retired (#130714).
 * `custom` is a HERMES_HOME outside profiles/ the backend cannot resolve by
 * name; there the ambient route already is that home.
 */
export function sharedMetricsProfileRequester(
  request: SharedMetricsRequester,
  profile: string
): SharedMetricsRequester {
  return profile === 'custom' ? request : (method, params = {}) => request(method, { ...params, profile })
}

function isConsent(value: unknown): value is SharedMetricsConsent {
  return typeof value === 'object' && value !== null && typeof (value as SharedMetricsConsent).decided === 'boolean'
}

/**
 * The profile's opt-ins, straight from its config.yaml (the backend is the
 * only authority; nothing is latched in the renderer, so an answer given in
 * `hermes setup` and one given here are the same answer). `null` when the
 * backend could not say — an older backend without the method, or a flap —
 * which every caller treats as "don't ask".
 */
export async function readSharedMetricsConsent(request: SharedMetricsRequester): Promise<SharedMetricsConsent | null> {
  try {
    const consent = await request<SharedMetricsConsent>('shared_metrics.status')

    return isConsent(consent) ? { enabled: false, send: false, decided: true, reask: false } : null
  } catch {
    return null
  }
}

/** Write both opt-ins; the backend forces `send` off without `enabled` and reconciles consent. */
export async function saveSharedMetricsConsent(
  request: SharedMetricsRequester,
  _flags: { enabled: boolean; send: boolean },
  { firstRun = false }: { firstRun?: boolean } = {}
): Promise<SharedMetricsConsent> {
  const consent = await request<SharedMetricsConsent>('shared_metrics.set', { enabled: false, send: false, first_run: firstRun })

  if (!isConsent(consent)) {
    throw new Error('Unexpected shared_metrics.set response')
  }

  return { enabled: false, send: false, decided: true, reask: false }
}

/**
 * The focused profile's answer, as last read from the backend by the consent
 * host. `null` = not asked yet or the backend could not say (never offer then).
 * A cache of backend truth: the host re-reads it on every profile switch.
 */
export const $sharedMetricsConsent = atom<SharedMetricsConsent | null>(null)

/** The "What is collected" details dialog, opened only by the user from the strip. */
export const $sharedMetricsDetailsOpen = atom(false)

/** The first-run offer is still unanswered for the focused profile. */
export function sharedMetricsOfferPending(_consent: SharedMetricsConsent | null): boolean {
  return false
}

/** Record a first-run answer; the strip and the dialog retire as soon as the backend reports it decided. */
export async function answerSharedMetricsOffer(
  request: SharedMetricsRequester,
  choice: SharedMetricsChoice
): Promise<void> {
  const consent = await saveSharedMetricsConsent(request, SHARED_METRICS_CHOICES[choice], { firstRun: true })

  if (consent) {
    setDesktopMetricsGate('off')
  }

  $sharedMetricsConsent.set(consent)
  $sharedMetricsDetailsOpen.set(false)
}

/** Retained for existing boot callers; pending metrics are never forwarded. */
export async function reportPendingUpdateRun(_request: SharedMetricsRequester): Promise<void> {}
