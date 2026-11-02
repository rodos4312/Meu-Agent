declare module 'semver' {
  export function valid(version: string): string | null
  export function gt(version: string, other: string): boolean
  export class SemVer {
    constructor(version: string)
    readonly version: string
  }
}
