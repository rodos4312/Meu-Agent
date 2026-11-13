import { gt, valid } from 'semver'

import releasePolicy from '../../meu-release.cjs'

/**
 * Meu update channels. A build's channel is baked into its install stamp (its trust anchor);
 * `updates.json` `channel` is the user's preference, which only decides what is offered:
 *
 *   stable → stable  automatic (with the user's consent, as before)
 *   stable → rc      blocked: an RC is never offered to, or installed on, a stable build
 *   rc     → rc      manual: RC releases live in a private repository (no automatic install)
 *   rc     → stable  automatic, only to a strictly newer stable release
 *
 * Versions are semver plus a per-channel grammar (stable `X.Y.Z` / `X.Y.Z-dev.N`, RC `X.Y.Z-rc.N`), so
 * one ordering (semver, the same one NSIS and electron-updater use) decides every comparison:
 * `0.1.0-dev.34 < 0.1.0-rc.1 < 0.1.0-rc.2 < 0.1.0`.
 */
export type MeuUpdateChannel = 'stable' | 'rc'

export type MeuChannelSpec = (typeof releasePolicy.UPDATE_CHANNELS)[MeuUpdateChannel]

export const STABLE_CHANNEL: MeuChannelSpec = releasePolicy.UPDATE_CHANNELS.stable

export function meuChannelSpec(channel: MeuUpdateChannel): MeuChannelSpec {
  return releasePolicy.UPDATE_CHANNELS[channel]
}

/** The channel an install stamp or manifest identity belongs to; null for a foreign identity. */
export function meuChannelOf(authority: { repository: string; branch: string; channel: string } | null | undefined) {
  return releasePolicy.channelForAuthority(authority) as MeuChannelSpec | null
}

export function isMeuChannelVersion(version: unknown, spec: MeuChannelSpec): version is string {
  return typeof version === 'string' && valid(version) === version && spec.versionPattern.test(version)
}

/** The saved preference; missing or unknown values keep the build's own channel, so no install drifts to RC. */
export function meuChannelPreference(value: unknown, build: MeuUpdateChannel): MeuUpdateChannel {
  return value === 'stable' || value === 'rc' ? value : build
}

export type MeuTransition =
  | { allowed: true }
  | { allowed: false; reason: 'malformed-version' | 'rc-on-stable' | 'not-newer' }

/** Whether `to` may replace `from`. Never a downgrade, never an RC onto a stable build. */
export function meuTransition(
  from: { channel: MeuUpdateChannel; version: string },
  to: { channel: MeuUpdateChannel; version: string }
): MeuTransition {
  if (!isMeuChannelVersion(from.version, meuChannelSpec(from.channel)) || !isMeuChannelVersion(to.version, meuChannelSpec(to.channel))) {
    return { allowed: false, reason: 'malformed-version' }
  }
  if (from.channel === 'stable' && to.channel === 'rc') {
    return { allowed: false, reason: 'rc-on-stable' }
  }
  if (!gt(to.version, from.version)) {
    return { allowed: false, reason: 'not-newer' }
  }
  return { allowed: true }
}

/** Where a manually installed RC is published; offered only when the preference is RC. Never fetched. */
export function meuRcReleasesUrl(preference: MeuUpdateChannel): string | null {
  return preference === 'rc' ? `https://github.com/${meuChannelSpec('rc').repository}/releases` : null
}
