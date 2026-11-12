import { describe, expect, it } from 'vitest'

import { enBoot } from '../src/i18n/en_boot.ts'

import { shownStartupTitlesExpression, startupScreenFailures, STARTUP_FAILURE_TITLES } from './smoke-browser-host-screens.mjs'

const BOOT_FAILED = enBoot.boot.failure.title
const SIGN_IN = enBoot.boot.failure.webappTitle

/** Runs the page-side expression against a page whose visible text is `innerText`. */
function shownTitles(innerText) {
  return new Function('document', `return ${shownStartupTitlesExpression}`)({ body: { innerText } })
}

describe('browser smoke startup screens', () => {
  it('knows the boot-failure and sign-in titles the renderer shows', () => {
    expect(STARTUP_FAILURE_TITLES).toContain(BOOT_FAILED)
    expect(STARTUP_FAILURE_TITLES).toContain(SIGN_IN)
  })

  it('finds the boot-failure screen on the page', () => {
    const titles = shownTitles(`${BOOT_FAILED}\nThe background service didn't come up.\nRetry`)

    expect(titles).toEqual([BOOT_FAILED])
    expect(startupScreenFailures(titles, { allowGatewayFailure: false })).toEqual([
      `Webapp shows the boot-failure screen ("${BOOT_FAILED}")`
    ])
  })

  it('finds the Webapp sign-in screen on the page', () => {
    const titles = shownTitles(`${SIGN_IN}\nRun hermes webapp on this computer to sign this browser in.`)

    expect(startupScreenFailures(titles, { allowGatewayFailure: false })).toEqual([
      `Webapp shows the sign-in screen ("${SIGN_IN}")`
    ])
  })

  it('tolerates the boot-failure screen only when a gateway failure is allowed', () => {
    const titles = shownTitles(BOOT_FAILED)

    expect(startupScreenFailures(titles, { allowGatewayFailure: true })).toEqual([])
  })

  it('fails on the sign-in screen even when a gateway failure is allowed', () => {
    const titles = shownTitles(SIGN_IN)

    expect(startupScreenFailures(titles, { allowGatewayFailure: true })).toHaveLength(1)
  })

  it('passes a ready Webapp', () => {
    const titles = shownTitles('New session\nAsk Hermes anything')

    expect(titles).toEqual([])
    expect(startupScreenFailures(titles, { allowGatewayFailure: false })).toEqual([])
  })
})
