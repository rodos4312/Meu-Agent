import type { KeyObject } from 'node:crypto'

export interface ReleasePayload {
  schema: number
  repository: string
  branch: string
  channel: string
  version: string
  commit: string
  publisherName: string
  file: string
  size: number
  sha256: string
  sha512: string
  signature?: string
}

export function publicKey(value: string): KeyObject
export function verifyRelease(release: ReleasePayload, pinnedKey: string): void
export function signRelease<T extends ReleasePayload>(
  release: T,
  privateKey: string | Buffer | KeyObject,
  pinnedKey: string
): T & { signature: string }
