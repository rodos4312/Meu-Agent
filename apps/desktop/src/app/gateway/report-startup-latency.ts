type GatewayRequest = (
  method: 'shared_metrics.startup_latency',
  params: { elapsed_ms: number; launch_id: string; surface: 'desktop_attach' }
) => Promise<unknown>

/** Kept for existing boot callers; Meu never reports launch telemetry. */
export async function reportStartupLatency(
  _desktop: Pick<Window['hermesDesktop'], 'claimStartupLatency'> | undefined,
  _request: GatewayRequest
): Promise<void> {}
