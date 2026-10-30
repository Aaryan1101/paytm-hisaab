"""Per-turn trace: which path answered, and how long each model/tool step took. Stored with the reply for debugging."""
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field


@dataclass
class Step:
    kind: str  # llm | tool
    name: str
    ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class TurnTrace:
    engine: str = "native"
    source: str = ""
    steps: list[Step] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return round(sum(s.ms for s in self.steps), 1)

    @property
    def total_tokens(self) -> int:
        return sum((s.input_tokens or 0) + (s.output_tokens or 0) for s in self.steps)

    def add(self, kind: str, name: str, ms: float, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self.steps.append(Step(kind, name, round(ms, 1), input_tokens, output_tokens))

    @contextmanager
    def timed(self, kind: str, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(kind, name, (time.perf_counter() - start) * 1000)

    def to_dict(self) -> dict:
        return {"engine": self.engine, "source": self.source, "total_ms": self.total_ms, "total_tokens": self.total_tokens,
                "steps": [asdict(s) for s in self.steps]}
