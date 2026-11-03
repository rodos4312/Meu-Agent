import { type ProfileScope, profileScopeKey } from '@/hermes'
import { queryClient } from '@/lib/query-client'
import { readJson, writeJson } from '@/lib/storage'

import { MCP_CATALOG_KEY } from '../../mcp/mcp-status'
import type { LocalServerInput } from '../types'

// Only local MCP display data is persisted. Hosted account data must be read
// from its owner; it must never depend on a cached Nous identity.
type PersistedRead = 'bundled' | 'servers'
const STORAGE_PREFIX = 'meu.local-connectors.v1.'
const PERSIST_MAX_BYTES = 256 * 1024
interface PersistedEntry {
  at: number
  data: unknown
}
export interface QuerySeed<T> {
  initialData?: T
  initialDataUpdatedAt?: number
}
const keyFor = (scopeKey: string, read: PersistedRead) => `${STORAGE_PREFIX}${scopeKey}.${read}`

export function seedOptions<T>(scope: ProfileScope, read: PersistedRead): QuerySeed<T> {
  const entry = readJson<PersistedEntry>(keyFor(profileScopeKey(scope), read))

  if (!entry || !Number.isFinite(entry.at) || entry.data === undefined || entry.data === null) {
    return {}
  }

  // SAFETY: the caller owns the shape stored under this scope and read.
  return { initialData: entry.data as T, initialDataUpdatedAt: entry.at }
}

function store(scopeKey: string, read: PersistedRead, entry: PersistedEntry): void {
  if (JSON.stringify(entry).length <= PERSIST_MAX_BYTES) {
    writeJson(keyFor(scopeKey, read), entry)
  }
}

export function startConnectorPersistence(): () => void {
  return queryClient.getQueryCache().subscribe(event => {
    if (event.type !== 'updated' || event.action.type !== 'success') {
      return
    }
    const [root, scopeKey] = event.query.queryKey

    // oxlint-disable-next-line anti-slop/no-runtime-typeof -- SAFETY: query keys are unknown at the cache boundary.
    if (root !== MCP_CATALOG_KEY[0] || typeof scopeKey !== 'string') {
      return
    }
    const { data, dataUpdatedAt } = event.query.state

    if (data === undefined) {
      return
    }
    store(scopeKey, 'bundled', { at: dataUpdatedAt, data })
  })
}

interface ServerSeed {
  enabled: boolean
  name: string
}

function isSeed(value: unknown): value is ServerSeed {
  if (value === null || !(value instanceof Object)) {
    return false
  }
  // SAFETY: validate the minimal saved display data before handing it to the UI.
  const seed = value as Partial<ServerSeed>

  // oxlint-disable-next-line anti-slop/no-runtime-typeof -- SAFETY: localStorage is an untrusted boundary.
  return typeof seed.name === 'string' && typeof seed.enabled === 'boolean'
}

export function storeLocalServers(scope: ProfileScope, servers: readonly LocalServerInput[]): void {
  store(profileScopeKey(scope), 'servers', {
    at: Date.now(),
    data: servers.map(({ enabled, name }) => ({ enabled, name }))
  })
}

export function seedLocalServers(scope: ProfileScope): LocalServerInput[] {
  const { initialData } = seedOptions<unknown>(scope, 'servers')

  if (!Array.isArray(initialData)) {
    return []
  }

  return initialData.filter(isSeed).map(seed => ({ ...seed, status: 'unknown', target: '' }))
}
