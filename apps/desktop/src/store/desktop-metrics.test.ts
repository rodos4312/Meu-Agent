import { afterEach, expect, it, vi } from 'vitest'

import {
  $desktopMetricsGate,
  bindDesktopMetrics,
  flushDesktopMetrics,
  noteMessageSent,
  recordAction,
  recordFeatureUse,
  recordOnboarding,
  resetDesktopMetricsForTests,
  setDesktopMetricsGate,
  tickDesktopMetrics
} from './desktop-metrics'

afterEach(() => {
  resetDesktopMetricsForTests()
  window.localStorage.clear()
})

it('refuses collection and reports after an old backend enables telemetry or the profile changes', () => {
  const request = vi.fn()

  resetDesktopMetricsForTests()
  window.localStorage.clear()

  for (const profile of ['local|default', 'local|work']) {
    bindDesktopMetrics(request, profile)
    setDesktopMetricsGate('on')
    recordFeatureUse('terminal_pane')
    recordAction('composer.send', 'click')
    recordOnboarding('provider_setup', 'reached')
    noteMessageSent('sessions')
    tickDesktopMetrics()
    flushDesktopMetrics()
    expect($desktopMetricsGate.get()).toBe('off')
  }

  expect(request).not.toHaveBeenCalled()

  for (let index = 0; index < window.localStorage.length; index++) {
    expect(window.localStorage.getItem(window.localStorage.key(index)!)).toBe('null')
  }
})
