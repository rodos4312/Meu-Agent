import { useI18n } from '@/i18n'

import { ToggleRow } from './primitives'

/** Meu has a fixed privacy policy; profiles cannot opt into shared metrics. */
export function SharedMetricsSettings() {
  const { t } = useI18n()
  const copy = t.sharedMetrics

  return (
    <div className="grid gap-1" id="setting-shared-metrics">
      <ToggleRow
        checked={false}
        description={copy.sendDesc}
        disabled
        label={copy.sendLabel}
        onChange={() => undefined}
      />
    </div>
  )
}
