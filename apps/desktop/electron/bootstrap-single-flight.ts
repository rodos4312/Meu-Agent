/**
 * First-run installer is single-flight: gateway retries must share one install.
 * Clearing this promise on success AND failure allows an intentional retry
 * only after the previous run has actually ended.
 */
export class BootstrapSingleFlight<T> {
  private active: Promise<T> | null = null

  isRunning(): boolean {
    return this.active !== null
  }

  run(start: () => Promise<T>): Promise<T> {
    if (this.active) return this.active
    const run = Promise.resolve().then(start)
    this.active = run
    void run.then(
      () => { if (this.active === run) this.active = null },
      () => { if (this.active === run) this.active = null }
    )
    return run
  }
}
