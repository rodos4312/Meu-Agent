import { translateNow } from '@/i18n'

export type GatewayReconnectSource = 'manual' | 'restart-followthrough'

export interface GatewayReconnectOptions {
  /**
   * Why the reconnect is running. `'manual'` (default) is an explicit user
   * recovery — the handler may unconditionally re-dial, including retrying a
   * credential that requires sign-in. `'restart-followthrough'` is the
   * automatic hand-off after a gateway restart: the socket often SURVIVED
   * (the restart targets the messaging gateway, not this client's backend),
   * so the handler probes first instead of force-closing a healthy socket.
   */
  source?: GatewayReconnectSource
}

type GatewayReconnectHandler = (options?: GatewayReconnectOptions) => Promise<void> | void

interface ReconnectOwner {
  handler: GatewayReconnectHandler
  currentEpoch: () => number
}

let activeOwner: ReconnectOwner | null = null
let inFlight: { owner: ReconnectOwner; epoch: number; promise: Promise<void> } | null = null

export function registerGatewayReconnect(handler: GatewayReconnectHandler, currentEpoch = () => 0): () => void {
  const owner = { handler, currentEpoch }
  activeOwner = owner

  return () => {
    if (activeOwner === owner) {
      activeOwner = null
    }
  }
}

export function reconnectGateway(options?: GatewayReconnectOptions): Promise<void> {
  const owner = activeOwner

  if (!owner) {
    return Promise.reject(new Error('Gateway reconnect is unavailable'))
  }

  const epoch = owner.currentEpoch()

  if (inFlight?.owner === owner && inFlight.epoch === epoch) {
    return inFlight.promise
  }

  const promise = Promise.resolve()
    .then(() => {
      // A route selection may move before this microtask starts. Never let
      // the old click reconnect the newly selected conversation's owner.
      if (activeOwner !== owner || owner.currentEpoch() !== epoch) {
        throw new Error('Gateway selection changed before reconnect started')
      }

      return owner.handler(options)
    })
    .finally(() => {
      if (inFlight?.promise === promise) {inFlight = null}
    })

  inFlight = { owner, epoch, promise }

  return promise
}

/** Toast button that re-dials the active connection — attached wherever a
 *  send fails because Hermes is offline (sudo/secret/approval prompts …). */
export function reconnectAction(): { label: string; onClick: () => void } {
  return {
    label: translateNow('prompts.reconnect'),
    onClick: () => void reconnectGateway().catch(() => undefined)
  }
}
