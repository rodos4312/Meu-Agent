import { atom } from 'nanostores'

import { persistStore } from '@/lib/persist-store'
import { persistBoolean, storedBoolean } from '@/lib/storage'

const HIDE_THREAD_TIMELINE_STORAGE_KEY = 'hermes.desktop.hideThreadTimeline'

/** Desktop-local appearance preference, shared by all threads in this window. */
export const $hideThreadTimeline = atom(storedBoolean(HIDE_THREAD_TIMELINE_STORAGE_KEY, false))

persistStore(
  $hideThreadTimeline,
  (value, options) => persistBoolean(HIDE_THREAD_TIMELINE_STORAGE_KEY, value, options),
  false
)

export function setHideThreadTimeline(value: boolean) {
  $hideThreadTimeline.set(value)
}
