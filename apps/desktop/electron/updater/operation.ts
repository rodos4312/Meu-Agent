import type { UpdaterApplyResultWire, UpdaterStrategy } from './index'

/** Preserve one native selection across check/apply and one owner through handoff. */
export class UpdateOperation {
  private strategy: Promise<UpdaterStrategy | null> | undefined
  private applying: boolean = false
  private handedOff: boolean = false
  private recovered: boolean = false

  constructor(private readonly initialize: () => Promise<UpdaterStrategy | null>) {}

  resolve(): Promise<UpdaterStrategy | null> {
    this.strategy ??= this.initialize().catch((error: Error): never => {
      this.strategy = undefined
      throw error
    })

    return this.strategy
  }

  async apply(run: () => Promise<UpdaterApplyResultWire>): Promise<UpdaterApplyResultWire> {
    if (this.applying) {
      throw new Error('An update is already in progress.')
    }

    this.applying = true
    this.recovered = false
    let handedOff: boolean = false

    try {
      const result: UpdaterApplyResultWire = await run()
      handedOff = result.handedOff === true && !this.recovered
      this.handedOff = handedOff

      if (result.handedOff && this.recovered) {
        return { ...result, ok: false, handedOff: false }
      }

      return result
    } finally {
      if (!handedOff) {
        this.applying = false
      }
    }
  }

  /** A native installer failed asynchronously after apply had handed off. */
  async restoreAfterFailure(restore: () => Promise<void>): Promise<void> {
    try {
      await restore()
    } finally {
      this.recoverHandoff()
    }
  }

  recoverHandoff(): void {
    if (!this.applying) return
    this.recovered = true
    this.strategy = undefined
    // Recovery may finish before apply publishes its result. Keep ownership
    // until that pending call settles, without re-locking a failed handoff.
    if (!this.handedOff) return
    this.handedOff = false
    this.applying = false
  }
}
