"""Sending a run somewhere it can be looked at.

Everything in this package is **optional and additive**. The audit log in
``logs/agents.jsonl`` remains the record of what a run did: it is hash-chained,
verifiable offline, and written whether or not anything here is configured.
This is a second copy, for looking at rather than for proving.

The distinction matters and is worth stating once. A trace in a hosted service
is a row in somebody's database; it can be edited, and a run that relied on it
for evidence would have traded a tamper-evident record for a convenient one.
So an exporter here may add, and may never replace.

Nothing is imported unless it is configured, so ``dependencies = []`` in
`pyproject.toml` stays true and a run with no observability configured is the
same offline run it was before.
"""

from __future__ import annotations

from .base import GuardedSink, NullSink, RunSink

__all__ = ["GuardedSink", "NullSink", "RunSink", "build_sink"]


def build_sink(name: str | None = None, **options):
    """The sink named in ``observability.sink``, or one that does nothing.

    ``"none"`` is the default and is not a degraded mode: it is the shipped
    configuration, and every test but this package's own runs against it.
    """
    key = (name or "none").strip().lower()
    if key in ("", "none", "off"):
        return NullSink()
    if key == "langfuse":
        from .langfuse import LangfuseSink

        return LangfuseSink(**options)
    raise ValueError(
        f"unknown observability sink {name!r}; have 'none' and 'langfuse'"
    )
