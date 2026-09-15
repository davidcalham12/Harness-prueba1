"""Text generation, behind one interface.

The orchestrator never imports a concrete engine. It asks :func:`build_engine`
for the name in ``engine.name`` and gets something that satisfies
:class:`~novaforge.engines.base.Engine`, which is what lets the entire test
suite run offline and for free against ``mock`` while ``--engine anthropic``
runs the same stages against the real model.
"""

from __future__ import annotations

from .base import Completion, Engine, EngineError, Request
from .mock import MockEngine

__all__ = ["Completion", "Engine", "EngineError", "MockEngine", "Request", "build_engine"]


def build_engine(name: str, *, model: str, seed: int = 0, inject_drift: bool = True) -> Engine:
    """Look up an engine by the name in the config.

    Unknown names raise. Falling back to the mock would mean a typo in
    ``--engine`` silently produces a free, fake novel that looks real.
    """
    key = (name or "").strip().lower()
    if key == "mock":
        return MockEngine(model=model, seed=seed, inject_drift=inject_drift)
    if key == "anthropic":
        try:
            from .anthropic import AnthropicEngine
        except ImportError as exc:
            raise EngineError(
                "the anthropic engine is not implemented in this build; "
                "use --engine mock. (novaforge/engines/anthropic.py is missing)"
            ) from exc
        return AnthropicEngine(model=model)
    raise EngineError(f"unknown engine {name!r}; have 'mock' and 'anthropic'")
