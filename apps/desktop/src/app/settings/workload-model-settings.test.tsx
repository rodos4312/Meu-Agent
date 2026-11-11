import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('./delegation-model-provider-field', () => ({
  useOwnerCatalog: () => ({
    providers: [
      { slug: 'deepseek', name: 'DeepSeek', models: ['deepseek-v4-pro'] },
      { slug: 'zai', name: 'Z.ai', models: ['glm-5.3-flash'] },
      { slug: 'gemini', name: 'Gemini', models: ['gemini-3.6-flash'] }
    ]
  })
}))
vi.mock('./model-select', () => ({
  withActive: (models: string[]) => models,
  ModelSelect: ({
    'aria-label': label,
    value,
    onValueChange
  }: {
    'aria-label': string
    value: string
    onValueChange: (value: string) => void
  }) => <input aria-label={label} onChange={event => onValueChange(event.target.value)} value={value} />
}))

import { workloadDefaultsPatch, WorkloadModelSettings } from './workload-model-settings'

afterEach(cleanup)

it('saves three providers and all roles together without changing other roles', async () => {
  const routes = {
    routine: { provider: 'zai', model: 'glm-5.3-flash' },
    complex: { provider: 'deepseek', model: 'deepseek-v4-pro' },
    web: { provider: 'gemini', model: 'gemini-3.6-flash' },
    vision: { provider: 'zai', model: 'glm-5.3-flash' }
  }

  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <WorkloadModelSettings
      config={{ smart_model_routing: { enabled: true, routes } }}
      model="deepseek-v4-pro"
      onSave={onSave}
      provider="deepseek"
    />
  )
  fireEvent.change(screen.getByLabelText('Web research model'), { target: { value: 'gemini-3.8-flash' } })
  fireEvent.click(screen.getByText('Save workload models'))
  await waitFor(() =>
    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      provider: 'deepseek',
      base_model: 'deepseek-v4-pro',
      routes: { ...routes, web: { provider: 'gemini', model: 'gemini-3.8-flash' } }
    })
  )
})

it('existing DeepSeek Auto does not claim custom workload models are configured', () => {
  render(
    <WorkloadModelSettings
      config={{ smart_model_routing: { enabled: true } }}
      model="deepseek-v4-pro"
      onSave={vi.fn()}
      provider="deepseek"
    />
  )
  expect(screen.getByRole('switch', { name: 'Use workload models' }).getAttribute('aria-checked')).toBe('false')
  expect(screen.queryByLabelText('Complex tasks model')).toBeNull()
})

it('updates the coordinator with a sparse patch while preserving unrelated settings', () => {
  const routes = {
    routine: { provider: 'zai', model: 'glm-5.3-flash' },
    complex: { provider: 'deepseek', model: 'deepseek-v4-pro' }
  }

  const config = { memory: { enabled: true }, delegation: { backend: 'meu_coordinator', max_concurrent_children: 2 } }
  const policy = { enabled: true, routes }
  const result = workloadDefaultsPatch(config, 'smart_model_routing', policy)
  expect(result.patch).toEqual({ smart_model_routing: policy, delegation: { backend: 'meu_coordinator_general' } })
  expect(result.next.memory).toEqual(config.memory)
  expect(config.delegation.backend).toBe('meu_coordinator')
})
