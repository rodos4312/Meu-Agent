"""Phase 7 helpers: deterministic embedders that count their calls, and a scripted planner."""

from __future__ import annotations

from collections.abc import Sequence

from meu_coding.embeddings import EmbeddingVector, LocalSubwordEmbeddings, ProviderIdentity, normalize, subwords

# A tiny "concept space": words with the same meaning share a dimension, so a query can match
# code that uses none of its words (what a real embedding model does, deterministically).
CONCEPTS = {
    "reconnect": 0, "reconnection": 0, "retry": 0, "backoff": 0, "redial": 0, "resume": 0, "resum": 0, "link": 0,
    "fingerprint": 1, "digest": 1, "checksum": 1, "hash": 1,
    "cleanup": 2, "prune": 2, "discard": 2, "remove": 2, "finalize": 2,
    "payment": 3, "invoice": 3, "billing": 3, "charge": 3,
    "status": 4, "heartbeat": 4, "online": 4, "presence": 4,
}


class ConceptEmbeddings:
    """Counts embed calls and texts; the version can be bumped to simulate a model change."""

    def __init__(self, version: str = "concept-v1", dimension: int = 24) -> None:
        self.version = version
        self.dimension = dimension
        self.calls = 0
        self.texts: list[str] = []

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity("test", "concepts", self.version, self.dimension, "api")

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        self.calls += 1
        self.texts += list(texts)
        out = []
        for text in texts:
            values = [0.0] * self.dimension
            for word in subwords(text):
                index = CONCEPTS.get(word)
                if index is not None:
                    values[index] += 1.0
                else:  # other words spread over their own dimensions: unrelated texts stay apart
                    values[5 + sum(map(ord, word)) % (self.dimension - 5)] += 0.15
            out.append(normalize(values))
        return out


class CountingLocal(LocalSubwordEmbeddings):
    def __init__(self) -> None:
        super().__init__(64)
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts += list(texts)
        return super().embed(texts)


class FailingEmbeddings(ConceptEmbeddings):
    def embed(self, texts):
        from meu_coding.embeddings import EmbeddingUnavailable

        raise EmbeddingUnavailable("provider down")


def roadmap_reply(*milestones: dict) -> dict:
    return {"milestones": list(milestones)}


OBJECTIVE = "Add a small function `add` in calc/ops.py and a unit test"


def milestone(mid: str, title: str, depends_on=(), areas=("calc/ops.py", "tests/test_ops.py"),
              kind="implementation", risk="low") -> dict:
    return {"id": mid, "title": title, "objective": OBJECTIVE, "depends_on": list(depends_on),
            "expected_areas": list(areas), "acceptance_criteria": [f"{title} verified"], "tests": ["pytest -q"],
            "risk": risk, "complexity": "simple", "kind": kind}


class ScriptedPlanner:
    def __init__(self, roadmap: dict, revisions: list[dict] | None = None) -> None:
        self.roadmap = roadmap
        self.revisions = list(revisions or [])
        self.contexts: list[dict] = []
        self.revision_calls = 0

    def propose_roadmap(self, goal, context):
        self.contexts.append(context)
        return self.roadmap

    def propose_revision(self, roadmap, finished):
        self.revision_calls += 1
        return self.revisions.pop(0) if self.revisions else {"operations": [{"op": "keep"}]}


def planner_service(tmp_path, planner, memory=None, builders=None):
    from meu_coding.task_service import CodingTaskService, ModelBundle
    from tests.meu_coding.phase3_support import ScriptedModel, fake_adapter, fake_runner, good

    return CodingTaskService(
        models_factory=lambda: ModelBundle(None, ScriptedModel(list(builders or [good])), None,
                                           {"architect": "fake:strong", "coder": "fake:strong",
                                            "reviewer": "fake:strong"}, "models_by_workload"),
        adapter_factory=lambda: fake_adapter(fake_runner()), spawn=lambda fn, name: fn(),
        audit_directory=tmp_path / "audit", planner_factory=lambda: planner, memory=memory)


GOAL = "Improve sync reliability of `add` in calc/ops.py"
ROADMAP = roadmap_reply(
    milestone("m1", "Analyze failures", areas=["calc/ops.py", "tests/test_ops.py"], kind="analysis"),
    milestone("m2", "Improve state machine", depends_on=["m1"], areas=["calc/ops.py", "tests/test_ops.py"]),
    milestone("m3", "Add regression tests", depends_on=["m2"], areas=["tests/"], kind="tests"),
    milestone("m4", "Final review", depends_on=["m2", "m3"], kind="review"),
)
