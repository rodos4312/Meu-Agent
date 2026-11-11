import type { ModelOptionProvider } from '@hermes/shared'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { getGlobalModelOptions, getRecommendedDefaultModel } from '@/hermes'
import { useI18n } from '@/i18n'
import { Loader2 } from '@/lib/icons'
import { isSubmitEnter } from '@/lib/ime'
import { cn } from '@/lib/utils'
import { startManualLocalEndpoint, startManualOnboarding, startManualProviderOAuth } from '@/store/onboarding'
import type { HermesConfigRecord } from '@/types/hermes'

import { CONTROL_TEXT } from './constants'
import { getNested } from './helpers'
import { ListRow } from './primitives'

export function MainModelAutoMode({
  config,
  provider,
  supported,
  onChange,
  onRefresh
}: {
  config: HermesConfigRecord | undefined
  provider: string
  supported: boolean
  onChange: (key: string, value: boolean) => void
  onRefresh: () => void
}) {
  const { t } = useI18n()
  const m = t.settings.model

  if (provider !== 'deepseek' || !config || getNested(config, 'smart_model_routing.routes')) {
    return null
  }

  return (
    <ListRow
      action={
        supported ? (
          <Switch
            aria-label={m.autoMode}
            checked={getNested(config, 'smart_model_routing.enabled') === true}
            onCheckedChange={value => onChange('smart_model_routing.enabled', value)}
          />
        ) : (
          <Button onClick={onRefresh} size="sm" variant="textStrong">
            {m.updateBackend}
          </Button>
        )
      }
      description={supported ? m.autoModeDesc : m.autoUnavailable}
      title={m.autoMode}
    />
  )
}

export function MainProviderKey({
  draft,
  busy,
  ready,
  provider,
  onChange,
  onSave
}: {
  draft: string
  busy: boolean
  ready: boolean
  provider: string
  onChange: (value: string) => void
  onSave: () => void
}) {
  const { t } = useI18n()
  const m = t.settings.model

  return (
    <ListRow
      action={
        <div className="grid w-full min-w-0 max-w-full @2xl:w-72 justify-items-end gap-2">
          <Input
            aria-label={m.apiKey}
            autoComplete="off"
            className={cn('min-w-0', CONTROL_TEXT)}
            onChange={event => onChange(event.target.value)}
            onKeyDown={event => {
              if (isSubmitEnter(event) && draft.trim() && !busy) {
                onSave()
              }
            }}
            placeholder={t.settings.credentials.pasteLabelKey(provider)}
            spellCheck={false}
            type="password"
            value={draft}
          />
          <Button disabled={!draft.trim() || busy} onClick={onSave} size="sm">
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            {busy ? t.settings.credentials.saving : t.common.save}
          </Button>
        </div>
      }
      description={ready ? m.replaceKeyHint : m.addKeyHint}
      title={m.apiKey}
    />
  )
}

// Preserve the existing scoped setup ladder; endpoint providers do not use OAuth.
export function startMainProviderSetup(
  selectedProviderRow: ModelOptionProvider | undefined,
  selectedProvider: string,
  scopeProfile?: string
) {
  const rowSlug = selectedProviderRow?.slug.trim() ?? ''
  const slug = rowSlug || selectedProvider.trim()

  if (!slug) {
    return
  }

  const lower = slug.toLowerCase()

  if (lower === 'custom' || lower === 'local' || lower.startsWith('custom:')) {
    startManualLocalEndpoint(null, scopeProfile)
  } else if (rowSlug) {
    startManualProviderOAuth(rowSlug, scopeProfile)
  } else {
    // An absent row has no trustworthy auth metadata. Open the generic
    // provider picker instead of deep-linking an unknown or stale slug.
    startManualOnboarding(undefined, scopeProfile)
  }
}

export async function loadProviderAfterKeySave(slug: string, profile?: string) {
  let recommended = ''

  try {
    recommended = (await getRecommendedDefaultModel(slug, profile)).model || ''
  } catch {
    // A credential save still succeeds when default-model curation is unavailable.
  }

  const options = await getGlobalModelOptions(undefined, profile)

  return {
    providers: options.providers || [],
    model: recommended || options.providers?.find(p => p.slug === slug)?.models?.[0] || ''
  }
}

export function MainProviderPicker({
  providers,
  value,
  onChange
}: {
  providers: readonly ModelOptionProvider[]
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useI18n()
  const m = t.settings.model

  return (
    <ListRow
      action={
        <Select onValueChange={onChange} value={value}>
          <SelectTrigger
            aria-label={m.provider}
            className={cn('w-full min-w-0 max-w-full @2xl:w-72 [&_[data-slot=select-value]]:truncate', CONTROL_TEXT)}
          >
            <SelectValue placeholder={m.provider} />
          </SelectTrigger>
          <SelectContent>
            {providers.map(provider => (
              <SelectItem key={provider.slug || 'none'} value={provider.slug || 'none'}>
                {provider.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
      title={m.provider}
    />
  )
}
