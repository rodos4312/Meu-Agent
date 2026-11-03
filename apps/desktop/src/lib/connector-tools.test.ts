import { describe, expect, it } from 'vitest'

import { mcpTargets } from './connector-tools'

describe('MCP operation rendering', () => {
  it('recognizes server names and object targets for independent MCP actions', () => {
    expect(
      mcpTargets('manage_connections', {
        action: 'install',
        connectors: ['Linear', { name: 'figma' }, { name: 'paper', mcp: true }]
      })
    ).toEqual([
      { name: 'linear', action: 'install' },
      { name: 'figma', action: 'install' },
      { name: 'paper', action: 'install' }
    ])
  })
  it('does not turn historical hosted calls into MCP installation requests', () => {
    expect(mcpTargets('manage_connections', { action: 'connect', connectors: ['gmail'] })).toEqual([])
    expect(
      mcpTargets('manage_connections', { action: 'install', connectors: [{ name: 'gmail', mcp: false }] })
    ).toEqual([])
  })
})
