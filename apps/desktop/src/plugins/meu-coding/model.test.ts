import { describe, expect, it } from 'vitest'

import {
  approvalFacts,
  type CodingTask,
  decisionParams,
  errorText,
  integrationFacts,
  integrationStatusText,
  parseDiff,
  PIPELINE,
  pipelineStep,
  routingFacts,
  shortFingerprint,
  stageTone
} from './model'

const FP = 'a'.repeat(32) + 'b'.repeat(32)

function task(overrides: Partial<CodingTask> = {}): CodingTask {
  return {
    actions: {
      approve: true,
      commit_confirm: false,
      commit_prepare: false,
      keep: false,
      reject: false,
      reject_proposal: true,
      repair: false
    },
    approval: {
      approval_id: 'id-1',
      changes: ['calc/ops.py: add add()'],
      fingerprint: FP,
      fingerprint_short: FP.slice(0, 16),
      proposed_diff:
        '--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,2 +1,4 @@\n+def add(a, b):\n+    return a + b\n def sub(a, b):\n',
      proposed_diff_truncated: false,
      review_rationale: 'all review rules passed',
      strategy: 'search_replace',
      strategy_reason: 'safe-default preference',
      target_files: ['calc/ops.py', 'tests/test_ops.py'],
      worktree_target: {
        base_commit: 'c'.repeat(40),
        branch: 'main',
        location: 'new isolated worktree',
        repo_root: '/r'
      }
    },
    attempts: [],
    busy: false,
    cleanup: {},
    commit: null,
    description: 'Add add()',
    error: '',
    execution: null,
    history: [],
    models: { coder: 'deepseek:pro' },
    plan: {
      assumptions: [],
      checks: [{ description: 'unit', kind: 'unit_test', targets: ['tests/test_ops.py'] }],
      files_to_change: ['calc/ops.py'],
      files_untouched: ['calc/__init__.py'],
      impact: {
        affected_tests: ['tests/test_ops.py'],
        callers: [],
        config: [],
        reasons: [],
        reverse_dependencies: 1,
        risk: 'low'
      },
      new_files: [],
      protected_paths: ['AGENTS.md'],
      questions: [],
      risk: 'low',
      steps: ['Change calc/ops.py'],
      summary: 'Add add()',
      symbols: []
    },
    project: '/r',
    restored: false,
    route_source: 'models_by_workload',
    stage: 'awaiting_approval',
    stage_label: 'Awaiting approval',
    task_id: 't-1',
    timings: {},
    ...overrides
  }
}

describe('approval view', () => {
  it('shows the full exact fingerprint and every approved fact', () => {
    const facts = Object.fromEntries(approvalFacts(task()).map(f => [f.label, f.value]))

    expect(facts.Fingerprint).toBe(FP)
    expect(facts['Target files']).toBe('calc/ops.py, tests/test_ops.py')
    expect(facts.Protected).toBe('AGENTS.md')
    expect(facts['Kept untouched']).toBe('calc/__init__.py')
    expect(facts['Edit strategy']).toContain('search_replace')
    expect(facts.Risk).toBe('LOW')
    expect(facts['Tests to run']).toContain('unit_test: tests/test_ops.py')
    expect(facts.Worktree).toContain('new isolated worktree')
    expect(shortFingerprint(FP)).toBe('aaaaaaaa…bbbbbbbb')
  })

  it('binds a decision to the approval on screen, never a vague permission', () => {
    expect(decisionParams(task(), 'approve', 'desktop')).toEqual({
      approval_id: 'id-1',
      decision: 'approve',
      device: 'desktop',
      fingerprint: FP,
      task_id: 't-1'
    })
    expect(decisionParams(task({ approval: null }), 'approve', 'desktop')).toBeNull()
    expect(decisionParams(task({ stage: 'executing' }), 'approve', 'desktop')).toBeNull()
    expect(decisionParams(task({ actions: { ...task().actions, approve: false } }), 'approve', 'desktop')).toBeNull()
  })
})

describe('diffs', () => {
  it('parses the approval preview form', () => {
    const [file] = parseDiff(task().approval!.proposed_diff)

    expect(file.path).toBe('calc/ops.py')
    expect([file.additions, file.deletions]).toEqual([2, 0])
  })

  it('parses git diffs with several files and keeps deleted "--" lines inside a hunk', () => {
    const files = parseDiff(
      [
        'diff --git a/a.py b/a.py',
        'index 1..2 100644',
        '--- a/a.py',
        '+++ b/a.py',
        '@@ -1 +1 @@',
        '--- old comment',
        '+new',
        'diff --git a/b.py b/b.py',
        '--- a/b.py',
        '+++ b/b.py',
        '@@ -1 +1 @@',
        '-x',
        '+y'
      ].join('\n')
    )

    expect(files.map(f => f.path)).toEqual(['a.py', 'b.py'])
    expect([files[0].additions, files[0].deletions]).toEqual([1, 1])
  })
})

describe('stages and errors', () => {
  it('orders the pipeline and colours outcomes', () => {
    expect(pipelineStep('analyzing')).toBe(0)
    expect(pipelineStep('committed')).toBeGreaterThan(pipelineStep('ready_to_commit'))
    expect(pipelineStep('blocked')).toBe(-1)
    expect(stageTone('awaiting_approval')).toBe('attention')
    expect(stageTone('blocked')).toBe('danger')
  })

  it('never shows a generic error', () => {
    expect(errorText(new Error('Proposal changed after approval — approval required again.'))).toContain('approval')
    expect(errorText(undefined)).toContain('Meu is running')
  })
})

describe('integration and routing views', () => {
  const preview = {
    base_commit: 'b'.repeat(40),
    changed_files: ['calc/ops.py'],
    conflicts: [],
    diff_stat: ' calc/ops.py | 4 ++++',
    drift_commits: ['abc123 docs: drift'],
    drift_files: ['README.md'],
    explanation: 'The target branch moved 1 commit(s).',
    overlapping_files: [],
    result_commit: 'r'.repeat(40),
    source_branch: 'hermes-subagent/subagent-coding-x',
    status: 'needs_rebase_or_replay' as const,
    strategies: ['APPLY_COMMIT', 'CHERRY_PICK_PREVIEW', 'CREATE_PR_PREVIEW'],
    target_branch: 'main',
    target_changed: true,
    target_head: 't'.repeat(40)
  }

  it('shows source, target, drift and conflicts before any integration', () => {
    const facts = Object.fromEntries(integrationFacts(preview).map(f => [f.label, f.value]))

    expect(facts.Source).toBe(`hermes-subagent/subagent-coding-x @ ${'r'.repeat(12)}`)
    expect(facts.Target).toBe(`main @ ${'t'.repeat(12)}`)
    expect(facts['Target changed']).toBe('yes — 1 commit(s)')
    expect(facts['Changed on target']).toBe('README.md')
    expect(facts['Possible conflicts']).toBe('none')
    expect(integrationStatusText('conflict')).toContain('blocked')
  })

  it('lists the model behind each role and why the coder was chosen', () => {
    const rows = routingFacts(
      task({
        routing: {
          architect: { route: 'deepseek:pro', source: 'models_by_workload:complex' },
          coder_used: {
            complexity: 'simple',
            reasons: ['small, low-risk change'],
            route: 'deepseek:flash',
            workload: 'coding.simple'
          },
          reviewer: { route: 'deepseek:pro', source: 'models_by_workload:complex' }
        }
      })
    )

    const facts = Object.fromEntries(rows.map(f => [f.label, f.value]))

    expect(facts.architect).toBe('deepseek:pro (models_by_workload:complex)')
    expect(facts['coder used']).toContain('coding.simple')
    expect(facts.reviewer).toContain('deepseek:pro')
  })

  it('includes integration in the pipeline but never a push or merge stage', () => {
    expect(PIPELINE).toContain('integrated')
    expect(PIPELINE.some(stage => /push|merge/.test(stage))).toBe(false)
    expect(stageTone('integration_preview')).toBe('attention')
  })
})
