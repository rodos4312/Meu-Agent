import { type ProfileScope, profileScopeKey } from '@/hermes'
import { queryClient } from '@/lib/query-client'

export const CONNECTORS_QUERY_ROOT = 'connectors'
export const CONNECTOR_GC_TIME = Number.POSITIVE_INFINITY
export const PLUGIN_SERVERS_STALE_TIME = 5 * 60 * 1000

const scoped = (scope: ProfileScope, ...rest: string[]) =>
  [CONNECTORS_QUERY_ROOT, profileScopeKey(scope), ...rest] as const

export const pluginServersQueryKey = (scope: ProfileScope) => scoped(scope, 'plugin-servers')
export const mcpOnboardingQueryKey = (scope: ProfileScope) => scoped(scope, 'mcp-onboarding')
export const pluginProbeQueryKey = (scope: ProfileScope, name: string) => scoped(scope, 'plugin-probe', name)

export function invalidatePluginProbe(scope: ProfileScope, name: string): void {
  void queryClient.invalidateQueries({ queryKey: pluginProbeQueryKey(scope, name) })
}

export function invalidateMcpConnections(scope: ProfileScope): void {
  void queryClient.invalidateQueries({ queryKey: pluginServersQueryKey(scope) })
  void queryClient.invalidateQueries({ queryKey: mcpOnboardingQueryKey(scope) })
}
