import type { BillingBlock } from '@hermes/shared/gateway-events'
import type { UsageLimit } from '@hermes/shared/plan-usage'

import { t } from '../i18n/runtime.js'

export interface BillingDialogCopy {
  cancelLabel: string
  confirmLabel: string
  detail: string
  title: string
}

/**
 * Copy for the out-of-credits confirm dialog (the TUI's billing wall). The
 * dialog is the actionable layer — the full provider guidance already lands in
 * the transcript — so `detail` stays to one concise, non-truncating line and the
 * confirm button opens the provider's
 * billing page (or `/model` to switch when we have no URL). Pure + exported so
 * the wording is unit-tested without driving the gateway.
 */
export function billingDialogCopy(block: BillingBlock): BillingDialogCopy {
  const label = block.provider_label || t('libText.billingDialog.yourProvider')

  return {
    cancelLabel: t('libText.billingDialog.dismiss'),
    confirmLabel: block.billing_url
      ? t('libText.billingDialog.openBillingPage')
      : t('libText.billingDialog.switchProvider'),
    detail: t('libText.billingDialog.providerDetail', label),
    title: t('libText.billingDialog.providerTitle', label)
  }
}

export interface UsageLimitDialog extends BillingDialogCopy {
  /** `/model` argument for the switch (this session only), or null: open the model picker. */
  switchValue: null | string
}

/** Recovery for a structured model limit, including archived plan refusals. */
export function usageLimitDialog(limit: UsageLimit): UsageLimitDialog {
  const suggestion = limit.suggestions?.[0]
  const sentence = (limit.message || '').trim()

  if (!suggestion) {
    return {
      cancelLabel: t('libText.billingDialog.dismiss'),
      confirmLabel: t('libText.billingDialog.switchProvider'),
      switchValue: null,
      detail: sentence,
      title: t('libText.billingDialog.limitTitle')
    }
  }

  const note = suggestion.note ? ` (${suggestion.note})` : ''

  return {
    cancelLabel: t('libText.billingDialog.dismiss'),
    confirmLabel: t('libText.billingDialog.limitSwitchTo', `${suggestion.label}${note}`),
    detail: sentence,
    switchValue: `${suggestion.model}${suggestion.provider ? ` --provider ${suggestion.provider}` : ''} --session`,
    title: t('libText.billingDialog.limitTitle')
  }
}
