"""Bounded Coder ↔ Reviewer repair loop.

One initial proposal plus at most ``max_repairs`` repairs, each driven by the Reviewer's
specific instructions. The loop stops on PASS, on BLOCK, when the attempts run out, when
a FIX carries no actionable instruction, or when the Coder repeats its previous proposal
(no progress). Every attempt is recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    RepairRequest,
    ReviewResult,
    ReviewStatus,
)

DEFAULT_MAX_REPAIRS = 3


@dataclass(frozen=True)
class Attempt:
    number: int  # 0 = initial proposal, 1.. = repairs
    proposal: CodeChangeProposal
    review: ReviewResult


@dataclass(frozen=True)
class RepairOutcome:
    attempts: tuple[Attempt, ...]
    stop_reason: str

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]

    @property
    def status(self) -> ReviewStatus:
        return self.final.review.status


ProposeFn = Callable[[RepairRequest | None], CodeChangeProposal]
ReviewFn = Callable[[CodeChangeProposal], ReviewResult]


class RepairLoop:
    def __init__(self, max_repairs: int = DEFAULT_MAX_REPAIRS) -> None:
        if max_repairs < 0:
            raise ValueError("max_repairs must be >= 0")
        self.max_repairs = max_repairs

    def run(self, propose: ProposeFn, review: ReviewFn,
            on_attempt: Callable[[Attempt], None] | None = None) -> RepairOutcome:
        attempts: list[Attempt] = []
        repair: RepairRequest | None = None
        for number in range(self.max_repairs + 1):
            proposal = propose(repair)
            result = review(proposal)
            attempt = Attempt(number, proposal, result)
            attempts.append(attempt)
            if on_attempt is not None:
                on_attempt(attempt)
            stop = _stop_reason(attempts)
            if stop:
                return RepairOutcome(tuple(attempts), stop)
            repair = RepairRequest(number + 1, proposal, result)
        return RepairOutcome(tuple(attempts), f"repair limit reached ({self.max_repairs} repairs)")


def _stop_reason(attempts: list[Attempt]) -> str | None:
    last = attempts[-1]
    if last.review.status == ReviewStatus.PASS:
        return "review passed"
    if last.review.status == ReviewStatus.BLOCK:
        return "review blocked the proposal"
    if not last.review.repair_instructions:
        return "review asked for fixes without actionable instructions"
    if len(attempts) > 1 and attempts[-2].proposal.operations == last.proposal.operations:
        return "no progress: the repair repeated the previous proposal"
    return None
