"""Loading the executable spec.

``specs/flow.yaml`` is not documentation that happens to be machine-readable.
:mod:`novaforge.orchestrator` loads it and runs it: stage order, gate
thresholds and failure policy exist there and nowhere else in the program.
"""

from __future__ import annotations

from .flow import FlowSpec, Gate, SpecError, Stage, load_flow
from .miniyaml import YamlError, safe_load

__all__ = ["FlowSpec", "Gate", "SpecError", "Stage", "YamlError", "load_flow", "safe_load"]
