import type { SharedMetricsRequester } from '@/store/shared-metrics'

interface SharedMetricsConsentDialogProps {
  enabled: boolean
  profile: string
  requestGateway: SharedMetricsRequester
}

/** Kept for layout callers; the Meu build has no telemetry opt-in dialog. */
export function SharedMetricsConsentDialog(_props: SharedMetricsConsentDialogProps) {
  return null
}
