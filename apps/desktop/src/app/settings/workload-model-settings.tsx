import type { ModelOptionProvider } from '@hermes/shared'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { ProfileScope } from '@/hermes'
import type { HermesConfigRecord } from '@/types/hermes'

import { useOwnerCatalog } from './delegation-model-provider-field'
import { getNested, setNested } from './helpers'
import { MainModelAutoMode } from './main-provider-key'
import { ModelSelect, withActive } from './model-select'
import { ListRow } from './primitives'

const ROLES = [
  ['routine', 'Light tasks'],
  ['complex', 'Complex tasks'],
  ['web', 'Web research'],
  ['vision', 'Images and screenshots']
] as const

interface Route {
  provider: string
  model: string
}
interface Policy {
  enabled?: boolean
  provider?: string
  base_model?: string
  routes?: Record<string, Route>
}

export function WorkloadModelSettings({
  config,
  provider,
  model,
  scope,
  onSave
}: {
  config: HermesConfigRecord
  provider: string
  model: string
  scope?: ProfileScope
  onSave: (value: Record<string, unknown>) => Promise<void>
}) {
  const { providers } = useOwnerCatalog(scope)
  const saved = (getNested(config, 'smart_model_routing') ?? {}) as Policy
  const [routes, setRoutes] = useState<Record<string, Route>>(saved.routes ?? {})
  const [enabled, setEnabled] = useState(saved.enabled === true && Boolean(saved.routes))
  const [saving, setSaving] = useState(false)
  const available = providers.filter(row => row.slug && row.slug !== 'moa')

  const valid =
    ['routine', 'complex'].every(role => routes[role]?.provider && routes[role]?.model) &&
    ['web', 'vision'].every(role => !routes[role]?.provider || Boolean(routes[role].model))

  async function save() {
    setSaving(true)

    try {
      await onSave({ ...saved, enabled, provider, base_model: model, routes })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-6 grid gap-2">
      <ListRow
        action={<Switch aria-label="Use workload models" checked={enabled} onCheckedChange={setEnabled} />}
        description="Choose a provider and model for each role. Add each provider's API key in Providers. Saved routes apply to new Auto chats and General Coordinator helpers."
        title="Models by workload"
      />
      {enabled &&
        ROLES.map(([role, label]) => {
          const route = routes[role] ?? { provider: '', model: '' }
          const selected = available.find(row => row.slug === route.provider)

          return (
            <ListRow
              action={
                <div className="grid w-full min-w-0 gap-2 @2xl:w-72">
                  <Select
                    onValueChange={value =>
                      setRoutes(current => ({
                        ...current,
                        [role]: value === '__main__' ? { provider, model } : { provider: value, model: '' }
                      }))
                    }
                    value={route.provider || '__choose__'}
                  >
                    <SelectTrigger aria-label={label + ' provider'}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem disabled value="__choose__">
                        Choose provider
                      </SelectItem>
                      <SelectItem value="__main__">Main model</SelectItem>
                      {available.map(row => (
                        <SelectItem key={row.slug} value={row.slug}>
                          {row.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <ModelSelect
                    aria-label={label + ' model'}
                    models={withActive(selected?.models ?? [], route.model)}
                    onValueChange={value =>
                      setRoutes(current => ({
                        ...current,
                        [role]: { ...route, model: value }
                      }))
                    }
                    provider={selected}
                    providerSlug={route.provider}
                    value={route.model}
                  />
                </div>
              }
              key={role}
              title={label}
            />
          )
        })}
      <div className="flex justify-end">
        <Button disabled={(enabled && !valid) || !provider || !model || saving} onClick={() => void save()} size="sm">
          {saving ? 'Saving…' : 'Save workload models'}
        </Button>
      </div>
    </div>
  )
}

export function workloadDefaultsPatch(
  config: HermesConfigRecord,
  key: string,
  value: boolean | string | Record<string, unknown>
) {
  let patch = setNested({}, key, value)
  let next = setNested(config, key, value)

  if (key === 'smart_model_routing' && typeof value === 'object' && value.enabled && value.routes) {
    patch = setNested(patch, 'delegation.backend', 'meu_coordinator_general')
    next = setNested(next, 'delegation.backend', 'meu_coordinator_general')
  }

  return { patch, next }
}

export function MainModelRoutingSettings({
  config,
  mainModel,
  catalogProvider,
  needsSetup,
  setupIsApiKey,
  onChange,
  onRefresh,
  scope
}: {
  config: HermesConfigRecord | undefined
  mainModel: { provider: string; model: string } | null
  catalogProvider?: ModelOptionProvider
  needsSetup: boolean
  setupIsApiKey: boolean
  onChange: (key: string, value: boolean | string | Record<string, unknown>) => Promise<void>
  onRefresh: () => void
  scope?: ProfileScope
}) {
  return (
    <>
      {needsSetup && !setupIsApiKey && catalogProvider && (
        <p className="mt-2 text-xs text-muted-foreground">
          {catalogProvider.auth_type === 'api_key'
            ? `${catalogProvider.name} needs an API key — set it up to choose a model.`
            : `${catalogProvider.name} signs in through your browser — Meu runs the flow for you.`}
        </p>
      )}
      <MainModelAutoMode
        config={config}
        onChange={onChange}
        onRefresh={onRefresh}
        provider={catalogProvider?.slug ?? ''}
        supported={catalogProvider?.automatic_routing === true}
      />
      {config && mainModel && (
        <WorkloadModelSettings
          config={config}
          key={String(scope ?? 'default')}
          model={mainModel.model}
          onSave={value => onChange('smart_model_routing', value)}
          provider={mainModel.provider}
          scope={scope}
        />
      )}
    </>
  )
}
