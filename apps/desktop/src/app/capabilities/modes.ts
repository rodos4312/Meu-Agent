export const CAPABILITY_MODES = ['skills', 'plugins', 'connectors', 'toolsets'] as const

export type CapabilityMode = (typeof CAPABILITY_MODES)[number]

/** Match the page's enum-query fallback, including old ?tab=hub links. */
export function capabilityModeFromSearch(search: string): CapabilityMode {
  const tab = new URLSearchParams(search).get('tab')

  return CAPABILITY_MODES.find(mode => mode === tab) ?? 'skills'
}
