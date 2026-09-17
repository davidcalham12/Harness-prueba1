"""Sending a run to Langfuse.

One trace per run, one generation per model call, one score per critic verdict.
That mapping is not a design decision so much as a recognition: the audit log
already had exactly those three shapes, so this module is a translation rather
than an instrumentation pass.

    logs/agents.jsonl              Langfuse
    ---------------------------    ------------------------------------
    the run                        a trace, named by slug
    event: call                    a generation, with usage and cost
    event: gate_decision           scores on that chapter's generation
    config_hash on every row       a tag, so runs can be compared
    cost.json                      cost_details, already per-call

**The credentials come from the environment only**, for the same reason the
Anthropic key does (SEC-2.1): a flag lands in shell history and in the process
table. `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and either
`LANGFUSE_BASE_URL` or `LANGFUSE_HOST` to pick a region or a self-hosted
instance - Langfuse's own docs name the first, the SDK names the second, and
reading only one of them sends US-region data to the EU default.

**Prompts and outputs are scrubbed before they leave the machine.** A premise
is user-supplied and a completion is model-written, and this is the one place
in the program where either travels to a third party. The redactor that
protects `state.json` protects this too — see SEC-2.2.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from ..prompts import langfuse_host
from ..security.secrets import Redactor
from .base import safely

__all__ = ["LangfuseSink", "MissingLangfuse"]

ENV_PUBLIC = "LANGFUSE_PUBLIC_KEY"
ENV_SECRET = "LANGFUSE_SECRET_KEY"
# Both names; see novaforge.prompts.HOST_ENV for why.
ENV_HOST = "LANGFUSE_BASE_URL or LANGFUSE_HOST"

# A prompt carries the whole Story Bible by the last chapter and there is no
# reason to ship all of it to a dashboard. Enough to recognise a call, not
# enough to be a second copy of the novel.
MAX_FIELD_CHARS = 4000


class MissingLangfuse(RuntimeError):
    """Langfuse was asked for and cannot be used."""


class LangfuseSink:
    """One trace per run, one generation per call, one score per verdict."""

    name = "langfuse"

    def __init__(self, *, report: Callable[[str], None] | None = None,
                 environment: str = "novaforge", **_: Any) -> None:
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise MissingLangfuse(
                "observability.sink is 'langfuse' but the SDK is not installed. "
                "pip install 'novaforge[langfuse]' — or set the sink back to "
                "'none', which is the shipped configuration and costs nothing."
            ) from exc

        public, secret = os.environ.get(ENV_PUBLIC), os.environ.get(ENV_SECRET)
        if not public or not secret:
            raise MissingLangfuse(
                f"{ENV_PUBLIC} and {ENV_SECRET} must both be set. They are read "
                f"from the environment only, for the same reason the Anthropic "
                f"key is (SEC-2.1).\n"
                f"  PowerShell: $env:{ENV_PUBLIC} = 'pk-lf-...'"
            )

        self._report = report or (lambda _: None)
        self._redactor = Redactor.from_env().with_literal(secret).with_literal(public)
        self._client = Langfuse(public_key=public, secret_key=secret,
                                host=langfuse_host(),
                                environment=environment)
        self._trace_id: str | None = None
        # Keyed by chapter, so a gate decision can be scored against the
        # generation that produced the draft it judged rather than the run.
        self._chapter_spans: dict[int, str] = {}
        self._slug = ""

    # -- helpers ---------------------------------------------------------

    def _clean(self, text: str) -> str:
        """Scrub, then truncate. In that order.

        Truncating first could cut a key in half and leave a fragment the
        patterns no longer recognise.
        """
        out = self._redactor.scrub(text or "")
        if len(out) > MAX_FIELD_CHARS:
            out = out[:MAX_FIELD_CHARS] + f"\n[... {len(out) - MAX_FIELD_CHARS} more characters]"
        return out

    # -- the interface ---------------------------------------------------

    def start_run(self, *, slug: str, premise: str, config_hash: str,
                  run_id: str, metadata: Mapping[str, Any]) -> None:
        def go() -> None:
            from langfuse import Langfuse

            self._slug = slug
            # Seeded from the attempt, not the novel. A resume carries the
            # same run_id and extends this trace; a replaced run brings a
            # new one. Seeding from slug and config alone put three
            # `--force` runs into a single trace with everything piled in.
            self._trace_id = Langfuse.create_trace_id(
                seed=run_id or f"{slug}|{config_hash}")
            # In SDK v4 the trace takes its name from its root observation, and
            # there is no public way to set trace-level tags: `update_trace` was
            # a v3 method and the only v4 route is a private one. So everything
            # a reader would have filtered on goes into metadata, which is
            # public, visible in the UI and will not vanish in a point release.
            span = self._client.start_observation(
                trace_context={"trace_id": self._trace_id},
                name=f"novel:{slug}",
                as_type="chain",
                input={"premise": self._clean(premise)},
                metadata={
                    "config_hash": config_hash,
                    "profile": metadata.get("profile") or "none",
                    "engine": metadata.get("engine") or "unknown",
                    **dict(metadata),
                },
            )
            span.end()
        safely(go, on_error=self._report)

    def record_call(self, *, flow_id: str, role: str, kind: str, model: str,
                    system: str, prompt: str, output: str,
                    input_tokens: int, output_tokens: int, cost_usd: float,
                    elapsed_s: float, metadata: Mapping[str, Any]) -> None:
        def go() -> None:
            generation = self._client.start_observation(
                trace_context={"trace_id": self._trace_id} if self._trace_id else None,
                name=f"{flow_id}:{role}",
                as_type="generation",
                model=model,
                input={"system": self._clean(system), "prompt": self._clean(prompt)},
                output=self._clean(output),
                usage_details={"input": input_tokens, "output": output_tokens},
                cost_details={"total": cost_usd},
                metadata={"flow_id": flow_id, "kind": kind, "role": role,
                          "elapsed_s": elapsed_s, **dict(metadata)},
            )
            chapter = metadata.get("chapter")
            if chapter is not None and kind == "chapter":
                self._chapter_spans[int(chapter)] = generation.id
            generation.end()
        safely(go, on_error=self._report)

    def record_gate(self, *, chapter: int, iteration: int,
                    scores: Mapping[str, int], threshold: int,
                    verdict: str, findings: Any) -> None:
        def go() -> None:
            observation = self._chapter_spans.get(int(chapter))
            for critic, value in sorted(scores.items()):
                self._client.create_score(
                    name=critic,
                    value=float(value),
                    data_type="NUMERIC",
                    trace_id=self._trace_id,
                    observation_id=observation,
                    comment=f"ch{chapter:02d} draft {iteration}: {verdict} "
                            f"(threshold {threshold})",
                    metadata={"chapter": chapter, "iteration": iteration,
                              "verdict": verdict, "threshold": threshold},
                )
        safely(go, on_error=self._report)

    def finish_run(self, *, state: Any, chain_intact: bool) -> None:
        def go() -> None:
            approved = sum(1 for c in getattr(state, "chapters", [])
                           if c.get("status") == "approved")
            self._client.create_score(
                name="chapters_approved",
                value=float(approved),
                data_type="NUMERIC",
                trace_id=self._trace_id,
                comment=f"{approved} of {len(getattr(state, 'chapters', []))} "
                        f"cleared the gate without warnings",
            )
            # The audit chain's verdict travels with the trace, so a reader
            # looking at the dashboard can see whether the *authoritative*
            # record - the one on disk - still verifies.
            self._client.create_score(
                name="audit_chain_intact",
                value="intact" if chain_intact else "broken",
                data_type="CATEGORICAL",
                trace_id=self._trace_id,
                comment="logs/agents.jsonl is the record; this is a copy",
            )
            self._client.flush()
            if self._trace_id:
                self._report(f"  langfuse  {self.url()}")
        safely(go, on_error=self._report)

    def url(self) -> str | None:
        if not self._trace_id:
            return None
        try:
            return self._client.get_trace_url(trace_id=self._trace_id)
        except Exception:  # noqa: BLE001 - a URL is a convenience, never a failure
            return None

    def check(self) -> bool:
        """Can these credentials reach the project? Used by the CLI, not a run."""
        try:
            return bool(self._client.auth_check())
        except Exception:  # noqa: BLE001
            return False
