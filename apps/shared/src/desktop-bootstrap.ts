export interface DesktopBootstrapStageDescriptor {
  name: string
  title?: string
  category?: string
  needs_user_input?: boolean
}

export type DesktopBootstrapStageState = 'pending' | 'running' | 'succeeded' | 'skipped' | 'failed'

export interface DesktopBootstrapStageResult {
  state: DesktopBootstrapStageState
  durationMs: number | null
  startedAt: number | null
  json: { ok: boolean; skipped?: boolean; reason?: string | null; stage: string } | null
  error: string | null
}

export interface DesktopBootstrapUnsupportedPlatform {
  platform: string
  activeRoot: string
  installCommand: string
  docsUrl: string
}

export interface DesktopBootstrapSetupChoice {
  platform: string
  activeRoot: string
  /** What the local card represents: 'none' = installer offer; the rest = use existing. */
  local: 'none' | 'installed' | 'bundled'
  /** This artifact is a bundled install (payload ships in-app). */
  bundled: boolean
}

export interface DesktopBootstrapState {
  revision?: number
  operation?: 'install' | 'upgrade'

  active: boolean
  manifest: {
    type: 'manifest'
    operation?: DesktopBootstrapState['operation']
    stages: DesktopBootstrapStageDescriptor[]
    protocolVersion: number | null
  } | null
  stages: Record<string, DesktopBootstrapStageResult>
  error: string | null
  failureStage?: string | null
  failureLogPath?: string | null
  log: Array<{ ts: number; stage: string | null; line: string; stream?: 'stdout' | 'stderr' }>
  startedAt: number | null
  completedAt: number | null
  setupChoice: DesktopBootstrapSetupChoice | null
  unsupportedPlatform: DesktopBootstrapUnsupportedPlatform | null
  /** This artifact is a bundled install (payload ships in-app). */
  bundled: boolean
}

export type DesktopBootstrapEvent = { revision?: number } & (
  | { type: 'dismissed' }
  | {
      type: 'setup-choice'
      active: boolean
      platform?: string
      activeRoot?: string
      local?: DesktopBootstrapSetupChoice['local']
      bundled?: boolean
    }
  | {
      type: 'manifest'
      operation?: DesktopBootstrapState['operation']
      stages: DesktopBootstrapStageDescriptor[]
      protocolVersion: number | null
    }
  | {
      type: 'stage'
      name: string
      state: DesktopBootstrapStageState
      durationMs?: number
      json?: DesktopBootstrapStageResult['json']
      error?: string | null
    }
  | { type: 'log'; stage?: string | null; line: string; stream?: 'stdout' | 'stderr' }
  | { type: 'complete'; marker: Record<string, unknown> }
  | { type: 'failed'; stage?: string | null; error: string; logPath?: string }
  | {
      type: 'unsupported-platform'
      platform: string
      activeRoot: string
      installCommand: string
      docsUrl: string
    }
)

export const EMPTY_BOOTSTRAP_STATE: DesktopBootstrapState = {
  operation: 'install',
  active: false,
  manifest: null,
  stages: {},
  error: null,
  log: [],
  startedAt: null,
  completedAt: null,
  setupChoice: null,
  unsupportedPlatform: null,
  bundled: false
}

function applySetupChoice(
  state: DesktopBootstrapState,
  ev: Extract<DesktopBootstrapEvent, { type: 'setup-choice' }>
): DesktopBootstrapState {
  return {
    ...state,
    active: false,
    manifest: null,
    stages: {},
    error: null,
    failureStage: null,
    failureLogPath: null,
    setupChoice: ev.active
      ? {
          platform: ev.platform || state.setupChoice?.platform || 'unknown',
          activeRoot: ev.activeRoot || state.setupChoice?.activeRoot || '',
          local: ev.local || state.setupChoice?.local || 'none',
          bundled: Boolean(ev.bundled)
        }
      : null,
    unsupportedPlatform: null,
    bundled: Boolean(ev.bundled)
  }
}

function applyStage(
  state: DesktopBootstrapState,
  ev: Extract<DesktopBootstrapEvent, { type: 'stage' }>,
  now: number
): DesktopBootstrapState {
  const prev = state.stages[ev.name]

  return {
    ...state,
    stages: {
      ...state.stages,
      [ev.name]: {
        state: ev.state,
        durationMs: ev.durationMs ?? null,
        // Stamp the start time on the running transition so the UI can show
        // a live elapsed timer; preserve it across repeated running events.
        startedAt: ev.state === 'running' ? (prev?.startedAt ?? now) : (prev?.startedAt ?? null),
        json: ev.json ?? null,
        error: ev.error ?? null
      }
    }
  }
}

function reduceBootstrapEvent(
  state: DesktopBootstrapState,
  ev: DesktopBootstrapEvent,
  now: number
): DesktopBootstrapState {
  if (ev.type === 'dismissed') {
    return { ...EMPTY_BOOTSTRAP_STATE }
  }

  if (ev.type === 'setup-choice') {
    return applySetupChoice(state, ev)
  }

  if (ev.type === 'manifest') {
    const stages: Record<string, DesktopBootstrapStageResult> = {}

    for (const stage of ev.stages) {
      stages[stage.name] = { state: 'pending', durationMs: null, startedAt: null, json: null, error: null }
    }

    return {
      ...state,
      active: true,
      operation: ev.operation ?? state.operation ?? 'install',
      manifest: { type: 'manifest', stages: ev.stages, protocolVersion: ev.protocolVersion },
      stages,
      error: null,
      failureStage: null,
      failureLogPath: null,
      setupChoice: null,
      startedAt: state.startedAt || now
    }
  }

  if (ev.type === 'stage') {
    return applyStage(state, ev, now)
  }

  if (ev.type === 'log') {
    const next = state.log.concat({ ts: now, stage: ev.stage ?? null, line: ev.line, stream: ev.stream })

    while (next.length > 500) {
      next.shift()
    }

    return { ...state, log: next }
  }

  if (ev.type === 'complete') {
    return { ...state, active: false, completedAt: now, error: null, failureStage: null, failureLogPath: null }
  }

  if (ev.type === 'failed') {
    return {
      ...state,
      active: false,
      error: ev.error || 'unknown error',
      failureStage: ev.stage ?? null,
      failureLogPath: ev.logPath ?? null,
      setupChoice: null
    }
  }

  if (ev.type === 'unsupported-platform') {
    return {
      ...state,
      active: false,
      setupChoice: null,
      unsupportedPlatform: {
        platform: ev.platform,
        activeRoot: ev.activeRoot,
        installCommand: ev.installCommand,
        docsUrl: ev.docsUrl
      }
    }
  }

  return state
}

/** One transition policy for Electron snapshots and the renderer's live progress. */
export function applyBootstrapEvent(
  state: DesktopBootstrapState,
  event: DesktopBootstrapEvent,
  now = Date.now()
): DesktopBootstrapState {
  if (event.revision !== undefined && state.revision !== undefined && event.revision <= state.revision) {
    return state
  }

  return { ...reduceBootstrapEvent(state, event, now), revision: event.revision ?? state.revision }
}
