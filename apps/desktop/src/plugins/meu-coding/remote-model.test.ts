import { describe, expect, it } from 'vitest'

import { mergeFacts, type MergePreview, pushFacts, type PushPreview, remoteApproveParams } from './remote-model'

const FP = 'a'.repeat(64)

const push: PushPreview = {
  changed_files: ['calc/ops.py'],
  destination_branch: 'hermes-subagent/x',
  expected_remote_sha: '',
  fingerprint: FP,
  force: 'FORBIDDEN',
  force_required: false,
  new_sha: 'b'.repeat(40),
  reason: '',
  refspec: 'refs/heads/hermes-subagent/x:refs/heads/hermes-subagent/x',
  remote: 'origin',
  remote_exists: false,
  remote_url: 'https://github.com/o/r.git',
  repository: 'github.com/o/r',
  risk: 'low',
  source_branch: 'hermes-subagent/x',
  source_commit: 'b'.repeat(40),
  status: 'ready',
  target_branch: 'main',
  tests: [{ check: 'unit', status: 'passed' }]
}

describe('remoteApproveParams', () => {
  it('names the exact kind and fingerprint and is always confirmed', () => {
    expect(remoteApproveParams('t1', 'merge', FP)).toEqual({
      confirmed: true,
      fingerprint: FP,
      kind: 'merge',
      task_id: 't1'
    })
  })

  it('refuses a missing or malformed fingerprint', () => {
    expect(() => remoteApproveParams('t1', 'push', '')).toThrow(/preview again/)
    expect(() => remoteApproveParams('t1', 'push', 'A'.repeat(64))).toThrow()
  })
})

describe('pushFacts', () => {
  it('shows the exact refspec, a new remote branch and force as forbidden', () => {
    const facts = Object.fromEntries(pushFacts(push).map(f => [f.label, f.value]))
    expect(facts.Refspec).toBe(push.refspec)
    expect(facts['Remote branch']).toBe('new branch')
    expect(facts['Force push']).toBe('FORBIDDEN')
    expect(facts['Target branch']).toContain('not pushed to')
  })

  it('makes a force requirement visible as a block', () => {
    const facts = Object.fromEntries(pushFacts({ ...push, force_required: true }).map(f => [f.label, f.value]))
    expect(facts['Force push']).toMatch(/forbidden, push blocked/)
  })
})

describe('mergeFacts', () => {
  it('summarises status, method, checks and reviews', () => {
    const merge: MergePreview = {
      allowed_methods: ['squash'],
      changed_files: ['a.py'],
      checks: { failed: 0, pending: 1, state: 'pending', total: 2 },
      conflicts: false,
      fingerprint: FP,
      method: 'squash',
      pr_number: 3,
      reasons: ['Checks are pending.'],
      repository: 'github.com/o/r',
      reviewer: 'pass',
      reviews: { approvals: 1, changes_requested: 0, reviewers: ['r'] },
      risk: 'low',
      source_sha: 'c'.repeat(40),
      status: 'blocked',
      target_branch: 'main',
      target_drift: false,
      target_sha: 'd'.repeat(40)
    }

    const facts = Object.fromEntries(mergeFacts(merge).map(f => [f.label, f.value]))
    expect(facts['Pull request']).toBe('#3')
    expect(facts.Status).toBe('Blocked')
    expect(facts.Checks).toContain('pending (2 total, 0 failed, 1 pending)')
    expect(facts.Reviews).toBe('1 approval(s), 0 change request(s)')
    expect(facts.Target).toBe(`main @ ${'d'.repeat(12)}`)
  })
})
