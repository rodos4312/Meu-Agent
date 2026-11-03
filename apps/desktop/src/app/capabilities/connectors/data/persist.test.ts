import { afterEach, describe, expect, it } from 'vitest'

import { profileScopeKey } from '@/hermes'
import { queryClient } from '@/lib/query-client'

import { MCP_CATALOG_KEY } from '../../mcp/mcp-status'

import { seedLocalServers, seedOptions, startConnectorPersistence, storeLocalServers } from './persist'

const scope = { connectionId: 'local', profile: 'work' }
const server = { enabled: true, name: 'my-tools', status: 'unknown', target: 'private-target' } as const

afterEach(() => {
  localStorage.clear()
  queryClient.clear()
})

describe('local MCP persistence without a Nous identity', () => {
  it('restores only display data and isolates profiles and connections', () => {
    storeLocalServers(scope, [server])
    expect(seedLocalServers(scope)).toEqual([{ enabled: true, name: 'my-tools', status: 'unknown', target: '' }])
    expect(seedLocalServers({ ...scope, profile: 'personal' })).toEqual([])
    expect(seedLocalServers({ ...scope, connectionId: 'remote' })).toEqual([])
    expect(JSON.stringify(localStorage)).not.toContain('private-target')
  })
  it('ignores legacy account caches', () => {
    localStorage.setItem('hermes.connectors.identity.v4', JSON.stringify('guest'))
    localStorage.setItem(
      `hermes.connectors.v4.${profileScopeKey(scope)}`,
      JSON.stringify({ identity: 'guest', servers: { at: 1, data: [server] } })
    )
    expect(seedLocalServers(scope)).toEqual([])
  })
  it('keeps the latest catalog when two updates share a timestamp', () => {
    const stop = startConnectorPersistence()
    const key = [MCP_CATALOG_KEY[0], profileScopeKey(scope)]
    try {
      queryClient.setQueryData(key, { entries: [{ name: 'first' }] }, { updatedAt: 123 })
      const latest = { entries: [{ name: 'second' }] }
      queryClient.setQueryData(key, latest, { updatedAt: 123 })
      expect(seedOptions(scope, 'bundled').initialData).toEqual(latest)
    } finally {
      stop()
    }
  })

  it('persists the bundled catalog but never hosted account data', () => {
    const stop = startConnectorPersistence()

    try {
      const catalog = { entries: [{ name: 'local-tool' }] }
      queryClient.setQueryData([MCP_CATALOG_KEY[0], profileScopeKey(scope)], catalog)
      queryClient.setQueryData(['connectors', profileScopeKey(scope), 'accounts'], { token: 'private-token' })
      expect(seedOptions(scope, 'bundled').initialData).toEqual(catalog)
      expect(JSON.stringify(localStorage)).not.toContain('private-token')
    } finally {
      stop()
    }
  })
})
