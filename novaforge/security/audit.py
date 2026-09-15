"""SEC-6 - the audit chain and the spend ceilings.

Two jobs that belong together because both answer "what did this run actually
do, and how much did it cost?".

**The chain.** ``logs/agents.jsonl`` is append-only, and every row carries the
SHA-256 hash of the row before it. :meth:`AuditChain.verify` detects any row
edited or removed in place.

**Stated limit, because it matters:** this is tamper-**evident**, not
tamper-**proof**. Anyone who can rewrite the whole file can recompute every
hash. Set ``NOVAFORGE_AUDIT_KEY`` in the environment and the chain becomes an
HMAC chain, unforgeable without that key. The absence of the key is recorded in
the genesis row, so a chain that was never keyed cannot later be presented as
one that was.

**The ceilings.** :class:`BudgetGuard` is checked *before* each call, not after.
A rewrite loop against a paid API is a loop that can bill, and discovering the
overrun afterwards is discovering it too late. Breaching a ceiling raises
:class:`BudgetExceeded`; the orchestrator saves state and stops, leaving the run
resumable. On resume the counters are restored from ``state.json``, so a limit
spans the whole run rather than resetting each time it is continued.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "AuditChain",
    "Budget",
    "BudgetExceeded",
    "BudgetGuard",
    "ChainReport",
    "GENESIS",
]

GENESIS = "0" * 64
_KEY_ENV = "NOVAFORGE_AUDIT_KEY"
# Fields the chain computes. Excluded when hashing, or the hash would have to
# contain itself.
_DERIVED = ("hash",)


def _canonical(row: Mapping[str, Any]) -> bytes:
    payload = {k: v for k, v in row.items() if k not in _DERIVED}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _digest(row: Mapping[str, Any], key: bytes | None) -> str:
    material = _canonical(row)
    if key:
        return hmac.new(key, material, hashlib.sha256).hexdigest()
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class ChainReport:
    """The result of verifying a chain."""

    rows: int
    intact: bool
    keyed: bool
    problems: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        if self.intact:
            kind = "HMAC chain" if self.keyed else "hash chain"
            return f"chain intact ({self.rows} rows, {kind})"
        return f"CHAIN BROKEN ({self.rows} rows): " + "; ".join(self.problems)


class AuditChain:
    """An append-only, hash-chained JSONL log inside the workspace."""

    def __init__(self, workspace, path: str = "logs/agents.jsonl",
                 *, key: str | None = None) -> None:
        self._workspace = workspace
        self._path = path
        raw = key if key is not None else os.environ.get(_KEY_ENV)
        self._key = raw.encode("utf-8") if raw else None
        self._last = GENESIS
        self._seq = 0
        if workspace.exists(path):
            self._resume_from_disk()

    @property
    def keyed(self) -> bool:
        return self._key is not None

    @property
    def path(self) -> str:
        return self._path

    def _resume_from_disk(self) -> None:
        """Pick up where an interrupted run left off, so a resumed run extends
        the chain rather than starting a second one beside it."""
        rows = self._read()
        if rows:
            self._last = str(rows[-1].get("hash", GENESIS))
            self._seq = int(rows[-1].get("seq", len(rows) - 1)) + 1

    def _read(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in self._workspace.read_lines(self._path):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_unparseable": line})
        return out

    def append(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Add one row, chained to the last. Returns the row as written."""
        entry = dict(row)
        entry["seq"] = self._seq
        entry["prev"] = self._last
        entry["hash"] = _digest(entry, self._key)
        self._workspace.append_line(
            self._path,
            line=json.dumps(entry, sort_keys=True, ensure_ascii=False),
        )
        self._last = entry["hash"]
        self._seq += 1
        return entry

    def verify(self) -> ChainReport:
        """Recompute the chain and report what, if anything, moved.

        Reports every problem rather than the first: "row 7 was edited" is
        usually less useful than "rows 7 and 12 were edited and row 9 is gone".
        """
        rows = self._read()
        problems: list[str] = []
        previous = GENESIS

        for index, row in enumerate(rows):
            if "_unparseable" in row:
                problems.append(f"row {index} is not valid JSON")
                previous = None  # cannot check the link past a corrupt row
                continue
            if row.get("seq") != index:
                problems.append(
                    f"row {index} has seq {row.get('seq')!r}; a row was inserted or removed"
                )
            if previous is not None and row.get("prev") != previous:
                problems.append(f"row {index} does not link to the row before it")
            recomputed = _digest(row, self._key)
            if row.get("hash") != recomputed:
                problems.append(f"row {index} was edited after it was written")
            previous = row.get("hash")

        return ChainReport(
            rows=len(rows),
            intact=not problems,
            keyed=self.keyed,
            problems=tuple(problems),
        )


class BudgetExceeded(RuntimeError):
    """A ceiling was reached. The run stops cleanly and stays resumable."""


@dataclass(frozen=True)
class Budget:
    """The ceilings, from ``budget`` in the config."""

    max_cost_usd: float
    max_calls: int
    max_tokens: int

    @classmethod
    def from_config(cls, config) -> "Budget":
        return cls(
            max_cost_usd=float(config.get("budget.max_cost_usd")),
            max_calls=int(config.get("budget.max_calls")),
            max_tokens=int(config.get("budget.max_tokens")),
        )


class BudgetGuard:
    """Enforces the ceilings, checked before every call."""

    def __init__(self, budget: Budget, *, spent_usd: float = 0.0,
                 calls: int = 0, tokens: int = 0) -> None:
        self.budget = budget
        self.spent_usd = float(spent_usd)
        self.calls = int(calls)
        self.tokens = int(tokens)

    @classmethod
    def resumed(cls, budget: Budget, state) -> "BudgetGuard":
        """Restore the counters from a previous run, so a ceiling spans the
        whole novel rather than resetting every time it is resumed."""
        return cls(
            budget,
            spent_usd=getattr(state, "cost_usd", 0.0),
            calls=getattr(state, "calls", 0),
            tokens=getattr(state, "input_tokens", 0) + getattr(state, "output_tokens", 0),
        )

    def check(self) -> None:
        """Raise if the *next* call would be one too many.

        Checked before the call, so the ceiling is a ceiling rather than a
        report of how far past it the run went.
        """
        if self.calls >= self.budget.max_calls:
            raise BudgetExceeded(
                f"call ceiling reached: {self.calls}/{self.budget.max_calls} "
                f"(budget.max_calls)"
            )
        if self.spent_usd >= self.budget.max_cost_usd:
            raise BudgetExceeded(
                f"cost ceiling reached: ${self.spent_usd:,.4f} of "
                f"${self.budget.max_cost_usd:,.2f} (budget.max_cost_usd)"
            )
        if self.tokens >= self.budget.max_tokens:
            raise BudgetExceeded(
                f"token ceiling reached: {self.tokens:,}/{self.budget.max_tokens:,} "
                f"(budget.max_tokens)"
            )

    def record(self, *, cost_usd: float, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.spent_usd += float(cost_usd)
        self.tokens += int(input_tokens) + int(output_tokens)

    @property
    def remaining(self) -> dict[str, float]:
        return {
            "cost_usd": round(max(0.0, self.budget.max_cost_usd - self.spent_usd), 6),
            "calls": max(0, self.budget.max_calls - self.calls),
            "tokens": max(0, self.budget.max_tokens - self.tokens),
        }

    def summary(self) -> str:
        return (f"${self.spent_usd:,.4f}/${self.budget.max_cost_usd:,.2f}, "
                f"{self.calls}/{self.budget.max_calls} calls, "
                f"{self.tokens:,}/{self.budget.max_tokens:,} tokens")
