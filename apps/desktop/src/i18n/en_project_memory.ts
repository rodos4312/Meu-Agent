export interface ProjectMemoryCopy {
  title: string
  description: string
  empty: string
  add: string
  edit: string
  remove: string
  note: string
  openFolder: string
  disabled: string
  saved: string
  unavailable: string
}

export const enProjectMemory: ProjectMemoryCopy = {
  title: 'Project notes',
  description: 'Decisions and preferences remembered for this project. Changes apply to new conversations.',
  empty: 'No saved notes for this project yet.',
  add: 'Add note',
  edit: 'Edit note',
  remove: 'Delete note',
  note: 'Note',
  openFolder: 'Open notes folder',
  disabled: 'Enable agent notes in Memory settings to use project notes.',
  saved: 'Saved. New conversations in this project will use these notes.',
  unavailable: 'Project notes need a newer backend. Update Meu to use this feature.'
}
