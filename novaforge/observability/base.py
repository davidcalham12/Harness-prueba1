"""What a sink is asked to do, and the one that does nothing.

The interface is deliberately small: a run starts, calls happen, the gate
decides, the run ends. That is the whole vocabulary, and it is the vocabulary
``logs/agents.jsonl`` already uses — a sink is a second reader of events the
orchestrator was emitting anyway, not a new thing for stages to remember.

**A sink may never change a run.** Every method returns ``None``, exceptions
are swallowed by :class:`RunSink.safely`, and no orchestrator decision reads
anything a sink returned. An observability backend that could fail a novel
would be a worse deal than no observability, and a hosted service is exactly
the kind of thing that is down on the afternoon you need to finish a book.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, runtime_checkable

__all__ = ["GuardedSink", "NullSink", "RunSink", "TalkativeSink", "safely"]


@runtime_checkable
class RunSink(Protocol):
    """Receives what a run did. Never influences it."""

    name: str

    def start_run(self, *, slug: str, premise: str, config_hash: str,
                  metadata: Mapping[str, Any]) -> None: ...

    def record_call(self, *, flow_id: str, role: str, kind: str, model: str,
                    system: str, prompt: str, output: str,
                    input_tokens: int, output_tokens: int, cost_usd: float,
                    elapsed_s: float, metadata: Mapping[str, Any]) -> None: ...

    def record_gate(self, *, chapter: int, iteration: int,
                    scores: Mapping[str, int], threshold: int,
                    verdict: str, findings: Any) -> None: ...

    def finish_run(self, *, state: Any, chain_intact: bool) -> None: ...

    def url(self) -> str | None: ...


class NullSink:
    """The default. Does nothing, quickly.

    Not a stub for something missing — it is the shipped configuration. A run
    with no observability is the offline, zero-dependency run the project
    promises, and this class is what makes "configured" and "not configured"
    the same code path rather than a branch at every call site.
    """

    name = "none"

    def start_run(self, **_: Any) -> None: ...
    def record_call(self, **_: Any) -> None: ...
    def record_gate(self, **_: Any) -> None: ...
    def finish_run(self, **_: Any) -> None: ...

    def url(self) -> str | None:
        return None


class GuardedSink:
    """Wraps any sink so that nothing it does can fail a run.

    The guarantee belongs here rather than inside each implementation. Putting
    it in the Langfuse sink protected Langfuse and nothing else: a sink written
    later, or a test double, could still take a novel down with it. Wrapping at
    the boundary makes it a property of *being* a sink.

    Found by a test that ran the pipeline against a sink which throws on every
    method. It killed the run.
    """

    def __init__(self, inner: "RunSink",
                 report: Callable[[str], None] | None = None) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "unknown")
        self._report = report or (lambda _: None)

    def _guard(self, method: str, **kwargs: Any) -> None:
        safely(lambda: getattr(self.inner, method)(**kwargs), on_error=self._report)

    def start_run(self, **kwargs: Any) -> None:
        self._guard("start_run", **kwargs)

    def record_call(self, **kwargs: Any) -> None:
        self._guard("record_call", **kwargs)

    def record_gate(self, **kwargs: Any) -> None:
        self._guard("record_gate", **kwargs)

    def finish_run(self, **kwargs: Any) -> None:
        self._guard("finish_run", **kwargs)

    def url(self) -> str | None:
        try:
            return self.inner.url()
        except Exception:  # noqa: BLE001 - a URL is a convenience, never a failure
            return None


class TalkativeSink(NullSink):
    """A sink that says one line when a run starts. Exists to be heard.

    Built through the same `build_sink` path as every other sink, so a test can
    check that the orchestrator hands over a reporter and the configured
    environment - the two things that were quietly missing.
    """

    name = "talkative"

    def __init__(self, *, report: Callable[[str], None] | None = None,
                 environment: str = "novaforge", **_: Any) -> None:
        self._report = report or (lambda _: None)
        self._environment = environment

    def start_run(self, **_: Any) -> None:
        self._report(f"  talkative sink speaking, environment={self._environment}")


def safely(action: Callable[[], None], *, on_error: Callable[[str], None] | None = None) -> None:
    """Run ``action``; report a failure and carry on.

    The one rule this package has. A hosted service that is slow, rate-limited
    or down must cost a run nothing, so every call into a sink goes through
    here. The failure is reported rather than swallowed silently — an operator
    who thinks a run is being traced and finds nothing later is worse off than
    one who saw a line saying it was not.
    """
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see above
        if on_error is not None:
            on_error(f"observability: {type(exc).__name__}: {exc}")
