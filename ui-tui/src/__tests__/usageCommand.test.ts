import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { sessionCommands } from '../app/slash/commands/session.js'
import { applyLocale, resetLocale, t } from '../i18n/runtime.js'

const usageCommand = sessionCommands.find(command => command.name === 'usage')!

function harness(usage: Record<string, unknown>) {
  const sys = vi.fn()
  const panel = vi.fn()
  const rpc = vi.fn(async () => usage)
  const run = async () => {
    usageCommand.run(
      '',
      {
        gateway: { rpc },
        sid: 'session',
        stale: () => false,
        transcript: { page: vi.fn(), panel, sys }
      } as never,
      'usage'
    )
    await rpc.mock.results[0]?.value
    await Promise.resolve()
  }
  return { panel, rpc, run, sys }
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => resetLocale())

describe('/usage without Nous payments', () => {
  it('uses the current locale for the empty-session message without a subscription promotion', async () => {
    applyLocale('xx', {
      lang: 'xx',
      surface: 'tui',
      messages: {
        'slashCmd.session.usage.noCalls': 'LOCAL-NO-CALLS',
        'slashCmd.session.usage.cta': 'OBSOLETE-PAYMENT-PROMOTION'
      }
    })
    const { rpc, run, sys } = harness({ calls: 0 })
    await run()
    expect(sys.mock.calls).toEqual([['LOCAL-NO-CALLS']])
    expect(rpc.mock.calls).toEqual([['session.usage', { session_id: 'session' }]])
  })

  it('shows local model and token totals without an additional account request', async () => {
    const { panel, rpc, run, sys } = harness({ calls: 2, input: 120, output: 30, total: 150, model: 'personal-model' })
    await run()
    expect(panel).toHaveBeenCalledWith(t('slashCmd.session.usage.usageTitle'), [
      {
        rows: [
          ['Model', 'personal-model'],
          ['Input tokens', '120'],
          ['Output tokens', '30'],
          ['Total tokens', '150'],
          ['API calls', '2']
        ]
      }
    ])
    expect(rpc.mock.calls).toEqual([['session.usage', { session_id: 'session' }]])
    expect(sys).not.toHaveBeenCalled()
  })

  it('ignores an older backend payment block while retaining its local usage result', async () => {
    const { panel, run, sys } = harness({
      calls: 0,
      credits_lines: ['OLD-NOUS-BALANCE'],
      credits_usage_window: true,
      usage: { available: true, plan_name: 'OLD-NOUS-PLAN' }
    })
    await run()
    expect(panel).not.toHaveBeenCalled()
    expect(sys.mock.calls).toEqual([[t('slashCmd.session.usage.noCalls')]])
  })
})
