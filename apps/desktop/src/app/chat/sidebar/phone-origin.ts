import type { SessionInfo } from '@/hermes'

// The MEU shell shows Greek where it has no locale catalog (see the settings
// screens), so this label is a constant rather than an i18n key.
export const PHONE_ORIGIN_FILTER_LABEL = 'Από κινητό'

/** The paired phone's label for a chat created there, or null: only the stored
 *  creation record counts, never the session's source. */
export function phoneOriginDevice(session: Pick<SessionInfo, 'origin'>): null | string {
  return session.origin?.kind === 'phone' ? session.origin.device : null
}

export function phoneOriginLabel(device: string): string {
  return device ? `${PHONE_ORIGIN_FILTER_LABEL}: ${device}` : PHONE_ORIGIN_FILTER_LABEL
}
