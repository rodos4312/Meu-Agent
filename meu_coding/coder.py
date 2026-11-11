"""Coder: asks a CodingModel for edits and packages them as a CodeChangeProposal.

The Coder never touches the repository. It picks the output format with the
EditStrategyRouter, hands the model the prepared context and plan (and, on a repair, the
Reviewer's instructions), then records the model's operations together with any
structural format errors. Applying a proposal is the execution layer's job, after review
and approval (``meu_coding.execution``).
"""

from __future__ import annotations

from dataclasses import replace

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    CodingModel,
    CodingRequest,
    CodingTask,
    EditAction,
    EditStrategy,
    ImplementationPlan,
    RepairRequest,
    StrategyChoice,
    TaskContext,
)
from meu_coding.edit_strategy import EditHint, EditStrategyRouter, format_errors


class Coder:
    def __init__(self, model: CodingModel, router: EditStrategyRouter | None = None,
                 requested_strategy: EditStrategy | None = None) -> None:
        self.model = model
        self.router = router or EditStrategyRouter()
        self.requested_strategy = requested_strategy

    def choose_strategy(self, task: CodingTask, plan: ImplementationPlan, context: TaskContext) -> StrategyChoice:
        only_new = bool(plan.new_files) and not plan.files_to_change
        sizes = [context.file_bytes.get(p, 0) for p in plan.files_to_change]
        largest = max(sizes) if sizes and all(sizes) else 0
        return self.router.select(task.model_id, EditHint(new_file=only_new, file_bytes=largest),
                                  self.requested_strategy)

    def propose(self, task: CodingTask, plan: ImplementationPlan, context: TaskContext,
                repair: RepairRequest | None = None) -> CodeChangeProposal:
        strategy = repair.previous.strategy if repair is not None else self.choose_strategy(task, plan, context)
        profile = self.router.profile_for(task.model_id)
        request = CodingRequest(task, plan, context, strategy, profile.max_context_chars, repair)
        output = self.model.propose(request)
        operations = tuple(output.operations)
        errors = [e for op in operations for e in format_errors(op)]
        # A new file is always written whole; any other mismatch is a format error.
        errors += [f"{op.path}: uses {op.strategy.value}, expected {strategy.strategy.value}"
                   for op in operations
                   if op.strategy != strategy.strategy and op.action != EditAction.DELETE
                   and not (op.strategy == EditStrategy.WHOLE_FILE and op.action == EditAction.CREATE)]
        proposal = CodeChangeProposal(
            operations=operations, strategy=strategy, assumptions=tuple(output.assumptions),
            expected_tests=tuple(output.expected_tests), notes=output.notes,
        )
        return replace(proposal, format_errors=tuple(errors))

