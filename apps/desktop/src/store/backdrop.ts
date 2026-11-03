import { atom } from 'nanostores'

import { persistStore } from '@/lib/persist-store'
import { persistBoolean, storedBoolean } from '@/lib/storage'

const KEY = 'hermes.desktop.backdrop.v1'

/** Whether the faint statue image renders behind the chat transcript. */
export const $backdrop = atom(storedBoolean(KEY, false))

persistStore($backdrop, (on, options) => persistBoolean(KEY, on, options), false)

export function setBackdrop(on: boolean) {
  $backdrop.set(on)
}
