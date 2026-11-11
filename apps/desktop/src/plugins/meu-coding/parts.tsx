/**
 * Small building blocks shared by the Coding page sections: section chrome, fact lists,
 * inline refusals, and the task-action hook that writes the backend's returned snapshot.
 */

import { useMutation, useQueryClient } from '@hermes/plugin-sdk'
import { type ReactNode, useState } from 'react'

import { type CodingTask, errorText } from './model'

export const TASK_KEY = (id: string) => ['meu-coding', 'task', id]
export const LIST_KEY = ['meu-coding', 'tasks']

export function InlineError({ title, description }: { title: string; description: string }) {
  return (
    <p className="rounded-[3px] bg-destructive/10 px-2 py-1 text-xs text-destructive" role="alert">
      <span className="font-semibold">{title}: </span>
      {description}
    </p>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-(--ui-stroke-secondary) pt-3">
      <h3 className="text-[0.6875rem] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  )
}

export function FactList({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(row => (
        <div className="contents" key={row.label}>
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="min-w-0 font-mono text-[0.7rem] break-all">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function useTaskAction(taskId: string) {
  const client = useQueryClient()
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (run: () => Promise<CodingTask>) => run(),
    onError: (err: unknown) => setError(errorText(err)),
    onSuccess: (task: CodingTask) => {
      setError('')
      client.setQueryData(TASK_KEY(taskId), task)
      void client.invalidateQueries({ queryKey: LIST_KEY })
    }
  })

  return { error, pending: mutation.isPending, run: (fn: () => Promise<CodingTask>) => mutation.mutate(fn) }
}
