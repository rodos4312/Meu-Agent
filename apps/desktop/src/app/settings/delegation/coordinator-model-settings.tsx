import { useState } from 'react'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ProfileScope } from '@/hermes'
import { useI18n } from '@/i18n'
import type { HermesConfigRecord } from '@/types/hermes'

import { useOwnerCatalog } from '../delegation-model-provider-field'
import { getNested, setNested } from '../helpers'
import { fromItemValue, toItemValue, withActive } from '../model-select'
import { ListRow } from '../primitives'

const SETTINGS = 'delegation.backends.meu_coordinator_general.models'
const AUTO = 'auto'
const WORKLOADS = ['routine', 'complex'] as const
type Workload = (typeof WORKLOADS)[number]
type ModelsByProvider = Record<string, Partial<Record<Workload, string>>>

export function CoordinatorModelSettings({
  config,
  onConfigChange,
  scope
}: {
  config: HermesConfigRecord
  onConfigChange: (config: HermesConfigRecord) => void
  scope: ProfileScope
}) {
  const { t } = useI18n()
  const copy = t.settings.model.subagents.routing.coordinator
  const { providers, query } = useOwnerCatalog(scope)
  const [picked, setPicked] = useState('')
  const available = providers.filter(p => p.authenticated !== false && p.slug !== 'moa' && p.models?.length)

  const active = available.find(p => p.slug === picked)
    ?? available.find(p => p.slug === query.data?.provider)
    ?? available[0]

  const saved = (getNested(config, SETTINGS) ?? {}) as ModelsByProvider

  if (!active) {
    return null
  }

  return (
    <div className="mt-4 grid gap-1">
      <ListRow
        action={
          <Select onValueChange={setPicked} value={active.slug}>
            <SelectTrigger aria-label={t.settings.model.provider}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {available.map(p => <SelectItem key={p.slug} value={p.slug}>{p.name}</SelectItem>)}
            </SelectContent>
          </Select>
        }
        description={copy.description}
        title={copy.title}
      />
      {WORKLOADS.map(workload => {
        const label = copy[workload]
        const current = saved[active.slug]?.[workload] ?? ''

        return (
          <ListRow
            action={
              <Select
                onValueChange={value => onConfigChange(setNested(config, SETTINGS, {
                  ...saved,
                  [active.slug]: { ...saved[active.slug], [workload]: fromItemValue(value) ?? '' }
                }))}
                value={toItemValue(current) || AUTO}
              >
                <SelectTrigger aria-label={label} className="w-full min-w-0 max-w-full @2xl:w-72">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO}>{copy.auto}</SelectItem>
                  {withActive(active.models ?? [], current).map(model => (
                    <SelectItem key={model} value={toItemValue(model)}>{model}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
            key={workload}
            title={label}
          />
        )
      })}
    </div>
  )
}
