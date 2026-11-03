import { useStore } from '@nanostores/react'
import { useQuery } from '@tanstack/react-query'
import { useRef } from 'react'
import { useNavigate } from 'react-router'

import { mcpOnboardingQueryKey } from '@/app/capabilities/connectors/data/keys'
import { listMcpServers, mcpServerStatus } from '@/app/capabilities/connectors/data/rpc'
import { useSessionView } from '@/app/chat/session-view'
import { CAPABILITIES_ROUTE } from '@/app/routes'
import { useConnectionOwner } from '@/components/assistant-ui/use-connection-owner'
import { Button } from '@/components/ui/button'
import { type ProfileScope, profileScopeKey } from '@/hermes'
import { useI18n } from '@/i18n'

export interface ConnectorDirectoryResult {
  connected: string[]
  newly_connected: string[]
  suggested: string[]
}
export interface ConnectorDirectoryCardProps {
  suggested?: readonly string[]
  onContinue: (result: ConnectorDirectoryResult) => void
}

export function ConnectorDirectoryCard(props: ConnectorDirectoryCardProps) {
  const storedId = useStore(useSessionView().$storedId)
  const owner = useConnectionOwner(storedId, true)

  return owner ? <LocalDirectory {...props} key={profileScopeKey(owner)} scope={owner} /> : null
}

function LocalDirectory({ onContinue, scope }: ConnectorDirectoryCardProps & { scope: ProfileScope }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const initial = useRef<null | string[]>(null)

  const servers = useQuery({
    queryKey: mcpOnboardingQueryKey(scope),
    queryFn: async () => {
      const [configured, runtime] = await Promise.all([listMcpServers(scope), mcpServerStatus(scope)])
      const enabled = new Set(configured.servers.filter(server => server.enabled).map(server => server.name))

      const connected = runtime.servers
        .filter(server => enabled.has(server.name) && server.status === 'connected')
        .map(server => server.name)

      initial.current ??= connected

      return connected
    },
    refetchOnWindowFocus: true,
    retry: false
  })

  const openDirectory = () => {
    const params = new URLSearchParams({ tab: 'connectors' })

    if (scope instanceof Object) {
      params.set('profile', scope.profile ?? '')

      if (scope.connectionId) {
        params.set('connection', scope.connectionId)
      }
    } else if (scope) {
      params.set('profile', scope)
    }

    navigate(`${CAPABILITIES_ROUTE}?${params}`)
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border p-4">
      <strong>{t.connectorsPage.title}</strong>
      {servers.isPending ? <p role="status">{t.connectorsPage.page.loading}</p> : null}
      {servers.error ? <p role="alert">{servers.error.message}</p> : null}
      {servers.data?.length ? <p>{servers.data.join(', ')}</p> : null}
      <Button disabled={servers.isFetching} onClick={() => void servers.refetch()} variant="outline">
        {t.connectorsPage.page.retry}
      </Button>
      <Button onClick={openDirectory} variant="outline">
        {t.connectorsPage.add.action}
      </Button>
      <Button
        disabled={servers.isFetching}
        onClick={() => {
          const connected = servers.error ? [] : (servers.data ?? [])
          onContinue({
            connected,
            newly_connected: connected.filter(name => !initial.current?.includes(name)),
            suggested: []
          })
        }}
      >
        {t.common.continue}
      </Button>
    </div>
  )
}
