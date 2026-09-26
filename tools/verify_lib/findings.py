"""The result types every check returns. See docs/guardrails.md."""

from dataclasses import asdict, dataclass

FAIL = "fail"
HUMAN = "needs_human"


@dataclass(frozen=True)
class Finding:
    check: str
    level: str
    message: str
    where: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def render(self) -> str:
        where = f"{self.where}: " if self.where else ""
        return f"[{self.check}] {where}{self.message}"
