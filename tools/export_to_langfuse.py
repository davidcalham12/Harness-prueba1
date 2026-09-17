"""Ship a finished run's log to Langfuse.

On `main`, observability was live: a `LangfuseSink` hung off the orchestrator's
single `_call` funnel and traced each model call as it happened. That
orchestrator is gone on this branch, and with it the sink.

This is the other shape of the same idea, and on reflection it is a better fit
for what this branch is: **the orchestrator writes a log, and a separate tool
ships it.** Three consequences worth stating, because two of them are gains:

* **It cannot fail a run.** `main` needed a `GuardedSink` wrapping every sink so
  that a dashboard being unreachable could never fail a novel. Here that
  guarantee is structural — this program runs after the novel exists, so the
  worst it can do is exit non-zero and leave the artefacts untouched.
* **It is re-runnable.** A run whose export failed can be exported again. A live
  sink gets one attempt at each call.
* **It is not live.** You cannot watch a run in the dashboard while it happens,
  which is a real loss if that was what you wanted the dashboard for.

Credentials come from the environment only, for the same reason the Anthropic
key did on `main` (SEC-2.1): a flag lands in shell history and in the process
table where any other local user can read it. There is no --api-key.

    LANGFUSE_PUBLIC_KEY   required
    LANGFUSE_SECRET_KEY   required
    LANGFUSE_BASE_URL     or LANGFUSE_HOST; both are read

Usage:

    python tools/export_to_langfuse.py output/<slug>
    python tools/export_to_langfuse.py output/<slug> --dry-run

`--dry-run` needs no credentials and no network: it prints what would be sent,
which is the fastest way to see whether the log has what you think it has.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Langfuse's own docs say LANGFUSE_BASE_URL; the SDK parameter is `host` and
# older material says LANGFUSE_HOST. Reading only one means anyone following the
# current docs sets a variable nothing reads, their region silently defaults to
# the EU, and the failure is an auth error that says nothing about regions.
HOST_ENV = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")

# Enough of a prompt to recognise a call, not a second copy of the novel.
MAX_FIELD_CHARS = 4000

# Key-shaped strings, scrubbed before anything leaves the machine. This is a
# smaller net than `main`'s Redactor: that one also caught bearer tokens and
# `api_key=` assignments. What it must catch here is the pair of keys this
# program is itself holding, which it does by literal as well as by pattern.
KEY_PATTERNS = [
    re.compile(r"\b(?:pk|sk)-lf-[A-Za-z0-9-]{8,}", re.I),
    re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{8,}", re.I),
]


def host() -> str | None:
    for name in HOST_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


class Scrubber:
    """Pattern-based, plus the live keys as literals."""

    def __init__(self, *literals: str) -> None:
        self._literals = [s for s in literals if s and len(s) > 8]

    def __call__(self, text: str) -> str:
        out = text or ""
        for literal in self._literals:
            out = out.replace(literal, "[REDACTED]")
        for pattern in KEY_PATTERNS:
            out = pattern.sub("[REDACTED]", out)
        if len(out) > MAX_FIELD_CHARS:
            out = out[:MAX_FIELD_CHARS] + f"\n[... {len(out) - MAX_FIELD_CHARS} more characters]"
        return out


def load_pricing(root: Path) -> dict:
    """`config/pricing.json`, or an empty table.

    Absent pricing is not an error. A generation then goes up with its token
    count and no cost, which is a gap a reader can see rather than a number
    they would have to distrust.
    """
    path = root / "config" / "pricing.json"
    if not path.exists():
        return {"models": {}, "assumed_input_share": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"models": data.get("models") or {},
            "assumed_input_share": data.get("assumed_input_share"),
            "source": data.get("_source", "")}


def cost_of(tokens: int, model: str, pricing: dict) -> dict | None:
    """What a call cost, as an estimate with both bounds.

    The harness reports one token figure per subagent call and does not split
    it into input and output, so this cannot be computed — only bounded. The
    bounds are real: every token at the input rate, and every token at the
    output rate. The estimate between them rests on `assumed_input_share`,
    which lives in the config because it is a judgement, not a measurement.

    Returning all three is the point. A reader who only sees the estimate has
    no way to tell how much of it is arithmetic.
    """
    rates = (pricing.get("models") or {}).get(model)
    share = pricing.get("assumed_input_share")
    if not rates or share is None or not tokens:
        return None

    per_input = rates["input_per_mtok"] / 1_000_000
    per_output = rates["output_per_mtok"] / 1_000_000
    low = tokens * per_input
    high = tokens * per_output
    estimate = tokens * (share * per_input + (1 - share) * per_output)
    return {"estimate": estimate, "if_all_input": low, "if_all_output": high,
            "assumed_input_share": share}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"no run log at {path}\nIs that a NovaForge workspace?")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            sys.exit(f"{path}:{number} is not JSON: {exc}")
    return rows


def load(workspace: Path) -> dict:
    rows = read_rows(workspace / "logs" / "agents.jsonl")
    state_path = workspace / "state.json"
    if not state_path.exists():
        sys.exit(f"no state.json in {workspace}")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    snapshot_path = workspace / "config.snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) \
        if snapshot_path.exists() else {}

    return {"rows": rows, "state": state, "snapshot": snapshot}


def chapter_text(workspace: Path, chapter: int) -> str:
    """The accepted draft, if it is on disk.

    Only the final accepted text survives a run — a rejected draft is not kept
    as prose, because the critique is what the gate acted on and what is worth
    keeping. So a generation for iteration 1 of a rejected chapter carries the
    findings, not the text it was judged on. That is a real limit of exporting
    after the fact rather than tracing live, and it is why the critique files
    matter.
    """
    path = workspace / "chapters" / f"ch{chapter:02d}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def critique(workspace: Path, chapter: int, critic: str, iteration: int) -> dict | None:
    path = workspace / "critiques" / f"ch{chapter:02d}.{critic}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.get("iterations", []):
        if entry.get("iteration") == iteration:
            return entry
    return None


def describe(data: dict) -> None:
    """--dry-run: what would be sent."""
    rows, state = data["rows"], data["state"]
    calls = [r for r in rows if r.get("agent")]
    gates = [r for r in rows if r.get("event") == "gate_decision"]

    print(f"trace       novel:{state.get('slug')}")
    print(f"  premise   {state.get('premise', '')[:70]}")
    print(f"  profile   {state.get('profile')}   config {state.get('config_hash')}")
    print(f"  stage     {state.get('stage')}")
    print()
    print(f"generations {len(calls)}")
    by_agent: dict[str, int] = {}
    for row in calls:
        by_agent[row["agent"]] = by_agent.get(row["agent"], 0) + 1
    for agent, count in sorted(by_agent.items(), key=lambda kv: -kv[1]):
        print(f"  {agent:<22}{count}")
    print()
    scores = sum(len(g.get("scores", {})) for g in gates)
    print(f"scores      {scores} from {len(gates)} gate decisions, "
          f"plus 2 run-level")
    for gate in gates:
        s = gate.get("scores", {})
        print(f"  ch{gate.get('chapter'):02d} draft {gate.get('iteration')}: "
              f"{', '.join(f'{k} {v}' for k, v in sorted(s.items()))}"
              f"  -> {gate.get('aggregate')} {gate.get('verdict')}")
    print()
    pricing = load_pricing(Path(__file__).resolve().parent.parent)
    tokens = sum(r.get("tokens") or 0 for r in calls)
    if not tokens:
        print("no token counts in this log, so nothing can be priced.")
        print("Runs driven before the orchestrator recorded `tokens` can be")
        print("filled in with tools/backfill_tokens.py.")
        return

    est = low = high = 0.0
    unpriced = []
    for row in calls:
        cost = cost_of(row.get("tokens") or 0, row.get("model") or "", pricing)
        if cost:
            est += cost["estimate"]
            low += cost["if_all_input"]
            high += cost["if_all_output"]
        elif row.get("tokens"):
            unpriced.append(row.get("model") or "(no model in row)")

    print(f"tokens      {tokens:,}")
    by_agent: dict[str, int] = {}
    for row in calls:
        by_agent[row["agent"]] = by_agent.get(row["agent"], 0) + (row.get("tokens") or 0)
    for agent, n in sorted(by_agent.items(), key=lambda kv: -kv[1]):
        share = n / tokens * 100
        print(f"  {agent:<22}{n:>8,}  {share:4.1f}%")
    print()
    print(f"cost        ${est:.2f} estimated")
    print(f"  bounds    ${low:.2f} if every token were input")
    print(f"            ${high:.2f} if every token were output")
    share = pricing.get("assumed_input_share")
    print(f"  basis     the harness reports one token total per call with no")
    print(f"            input/output split, so the bounds are exact and the")
    print(f"            estimate assumes {share:.0%} input "
          f"(config/pricing.json)")
    if unpriced:
        print(f"  unpriced  {len(unpriced)} generations: "
              f"{', '.join(sorted(set(unpriced)))}")

    sources = {r.get("tokens_source") for r in calls if r.get("tokens")}
    if "reconstructed" in sources:
        print()
        print("Some token figures are marked `reconstructed`: copied out of a")
        print("session transcript rather than recorded by the orchestrator as")
        print("the run happened. They travel with that label.")


def export(workspace: Path, data: dict, fresh: str = "") -> int:
    try:
        from langfuse import Langfuse
    except ImportError:
        sys.exit("the Langfuse SDK is not installed:  pip install langfuse\n"
                 "Or use --dry-run, which needs neither the SDK nor credentials.")

    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public or not secret:
        sys.exit(
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must both be set.\n"
            "They are read from the environment only, never from a flag.\n"
            "  PowerShell:  $env:LANGFUSE_PUBLIC_KEY = 'pk-lf-...'\n"
            "  bash:        export LANGFUSE_PUBLIC_KEY=pk-lf-..."
        )

    scrub = Scrubber(public, secret)
    client = Langfuse(public_key=public, secret_key=secret, host=host(),
                      environment="novaforge")

    # auth_check RAISES on bad credentials rather than returning False, which is
    # not what the name suggests and cost a traceback to discover. Catching it is
    # the difference between a stack trace and a line that says what to do.
    try:
        reachable = bool(client.auth_check())
        detail = ""
    except Exception as exc:  # noqa: BLE001 - anything here means "cannot reach"
        reachable, detail = False, str(exc)

    if not reachable:
        where = host() or "the EU default, https://cloud.langfuse.com"
        message = [f"those credentials cannot reach {where}."]
        if ("401" in detail or "Unauthorized" in detail) and not host():
            # A Langfuse key pair is valid on exactly one host, and the SDK
            # silently defaults to the EU. The 401 that follows says nothing
            # about regions unless you already suspect them.
            message += [
                "",
                "This is almost always the region rather than the keys. Neither",
                "LANGFUSE_BASE_URL nor LANGFUSE_HOST is set, so the SDK used the",
                "EU default. Set the host your project actually lives on — it is",
                "the one in your browser's address bar on the dashboard:",
                "",
                "  $env:LANGFUSE_BASE_URL = 'https://us.cloud.langfuse.com'",
                "  $env:LANGFUSE_BASE_URL = 'https://cloud.langfuse.com'",
            ]
        else:
            message += ["", "Check that the host matches the project's region."]
        sys.exit("\n".join(message))

    rows, state, snapshot = data["rows"], data["state"], data["snapshot"]
    slug = state.get("slug", "unknown")
    pricing = load_pricing(Path(__file__).resolve().parent.parent)

    # Totals first, so the trace's own metadata carries them. A reader who
    # opens a trace should see what the run cost without adding up its
    # children.
    totals = {"tokens": 0, "estimate": 0.0, "low": 0.0, "high": 0.0}
    per_agent: dict[str, int] = {}
    priced = unpriced = 0
    for row in rows:
        if not row.get("agent"):
            continue
        tokens = row.get("tokens") or 0
        totals["tokens"] += tokens
        per_agent[row["agent"]] = per_agent.get(row["agent"], 0) + tokens
        cost = cost_of(tokens, row.get("model") or "", pricing)
        if cost:
            priced += 1
            totals["estimate"] += cost["estimate"]
            totals["low"] += cost["if_all_input"]
            totals["high"] += cost["if_all_output"]
        else:
            unpriced += 1

    # Seeded from the attempt, not the novel. On `main` this was got wrong
    # three times before it stuck: seeding from slug and config alone put
    # every re-run of the same novel into one trace, with everything piled in.
    # A workspace has no run_id, so the log's first timestamp stands in for one.
    #
    # `--fresh` adds a salt. It exists because an export can be wrong — the
    # first export of this run went up with no token counts at all — and
    # re-running onto the same trace id appends a second copy of every
    # generation rather than replacing the first.
    first_ts = next((r.get("ts") for r in rows if r.get("ts")), "")
    seed = f"{slug}|{state.get('config_hash')}|{first_ts}"
    if fresh:
        seed += f"|export={fresh}"
    trace_id = Langfuse.create_trace_id(seed=seed)

    # In SDK v4 a trace takes its name from its root observation and there is no
    # public way to set trace-level tags, so everything a reader would filter on
    # goes into metadata, which is public and will not vanish in a point release.
    root = client.start_observation(
        trace_context={"trace_id": trace_id},
        name=f"novel:{slug}",
        as_type="chain",
        input={"premise": scrub(state.get("premise", ""))},
        metadata={
            "config_hash": state.get("config_hash"),
            "profile": state.get("profile"),
            "stage": state.get("stage"),
            "orchestrator": "claude-code",
            "branch": "claude-orchestrator",
            "chapters": len(state.get("chapters", [])),
            "manuscript_words": state.get("manuscript_words"),
            "style_passes_discarded": state.get("style_passes_discarded"),
            "gate": (snapshot.get("quality_gate") or {}),
            "total_tokens": totals["tokens"],
            "tokens_by_agent": per_agent,
            "cost_usd_estimate": round(totals["estimate"], 4),
            "cost_usd_if_all_input": round(totals["low"], 4),
            "cost_usd_if_all_output": round(totals["high"], 4),
            "generations_priced": priced,
            "generations_unpriced": unpriced,
            "pricing_source": pricing.get("source", ""),
        },
    )
    root.end()

    # Keyed by (chapter, iteration) so a gate decision can be scored against the
    # generation that produced the draft it judged, rather than against the run.
    drafts: dict[tuple[int, int], str] = {}
    sent = 0
    run_tokens = 0
    run_cost = {"estimate": 0.0, "low": 0.0, "high": 0.0}

    for row in rows:
        agent = row.get("agent")
        if not agent:
            continue

        chapter = row.get("chapter")
        iteration = row.get("iteration")
        is_draft = agent == "chapter-writer" and chapter is not None

        output = ""
        if is_draft and state.get("stage") == "complete":
            # Only the accepted draft survives; see chapter_text().
            final_iteration = max(
                (r.get("iteration") or 0) for r in rows
                if r.get("agent") == "chapter-writer" and r.get("chapter") == chapter
            )
            if iteration == final_iteration:
                output = chapter_text(workspace, chapter)
        elif agent.endswith("-critic") and chapter is not None:
            entry = critique(workspace, chapter, agent.replace("-critic", ""),
                             iteration or 1)
            if entry:
                output = json.dumps(entry, indent=2)

        name = f"{row.get('stage', 'FLOW-?')}:{agent}"
        if chapter is not None:
            name += f":ch{chapter:02d}"

        tokens = row.get("tokens") or 0
        model = row.get("model") or "claude-code-subagent"
        cost = cost_of(tokens, model, pricing)

        extra: dict = {}
        if tokens:
            # One figure, because one figure is what the harness reports. Sent
            # under "total" rather than split across input and output, which
            # would be inventing a breakdown Langfuse would then price as fact.
            extra["usage_details"] = {"total": tokens}
        if cost:
            extra["cost_details"] = {"total": round(cost["estimate"], 6)}

        generation = client.start_observation(
            trace_context={"trace_id": trace_id},
            name=name,
            as_type="generation",
            model=model,
            output=scrub(output),
            metadata={
                **{k: v for k, v in row.items() if k not in ("ts",)},
                **({"cost_usd_estimate": round(cost["estimate"], 6),
                    "cost_usd_if_all_input": round(cost["if_all_input"], 6),
                    "cost_usd_if_all_output": round(cost["if_all_output"], 6),
                    "cost_basis": f"one total token figure, split "
                                  f"{cost['assumed_input_share']:.0%} input by "
                                  f"assumption; the two bounds are exact"}
                   if cost else
                   {"cost_basis": "not priced: no rate for this model in "
                                  "config/pricing.json"}),
            },
            **extra,
        )
        run_tokens += tokens
        if cost:
            run_cost["estimate"] += cost["estimate"]
            run_cost["low"] += cost["if_all_input"]
            run_cost["high"] += cost["if_all_output"]
        if is_draft:
            drafts[(chapter, iteration or 1)] = generation.id
        generation.end()
        sent += 1

    for row in rows:
        if row.get("event") != "gate_decision":
            continue
        chapter, iteration = row.get("chapter"), row.get("iteration")
        observation = drafts.get((chapter, iteration))
        for critic, value in sorted((row.get("scores") or {}).items()):
            client.create_score(
                name=critic,
                value=float(value),
                data_type="NUMERIC",
                trace_id=trace_id,
                observation_id=observation,
                comment=f"ch{chapter:02d} draft {iteration}: {row.get('verdict')} "
                        f"(threshold {row.get('threshold')}, aggregate "
                        f"{row.get('aggregate')})",
                metadata={"chapter": chapter, "iteration": iteration,
                          "verdict": row.get("verdict"),
                          "reproducible": critic in ("length", "chatter")},
            )

    chapters = state.get("chapters", [])
    approved = sum(1 for c in chapters if c.get("status") == "approved")
    client.create_score(
        name="chapters_approved", value=float(approved), data_type="NUMERIC",
        trace_id=trace_id,
        comment=f"{approved} of {len(chapters)} cleared the gate without warnings",
    )
    client.create_score(
        name="gate_reproducible", value="no", data_type="CATEGORICAL",
        trace_id=trace_id,
        comment="continuity and science are model critics on this branch; "
                "length and chatter are arithmetic and do reproduce",
    )

    client.flush()

    scores_sent = sum(len(r.get("scores") or {}) for r in rows
                      if r.get("event") == "gate_decision") + 2
    print(f"sent {sent} generations and {scores_sent} scores")
    if totals["tokens"]:
        print(f"  {totals['tokens']:,} tokens")
        if priced:
            print(f"  ${totals['estimate']:.2f} estimated "
                  f"(${totals['low']:.2f} if every token were input, "
                  f"${totals['high']:.2f} if every token were output)")
        if unpriced:
            print(f"  {unpriced} generations unpriced; add their model to "
                  f"config/pricing.json")
    else:
        print("  no token counts in the log - nothing to price")
    try:
        print(client.get_trace_url(trace_id=trace_id))
    except Exception:  # noqa: BLE001 - a URL is a convenience, never a failure
        print(f"trace id: {trace_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ship a finished NovaForge run to Langfuse.")
    parser.add_argument("workspace", type=Path,
                        help="a run directory, e.g. output/<slug>")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent; no credentials, no network")
    parser.add_argument("--fresh", metavar="LABEL", default="",
                        help="mint a new trace instead of adding to the one this "
                             "run already has. Re-exporting onto the same trace "
                             "appends a second copy of every generation rather "
                             "than replacing the first, so use this when a "
                             "previous export was incomplete. The label is any "
                             "string, e.g. --fresh with-tokens")
    args = parser.parse_args(argv)

    workspace = args.workspace
    if not workspace.is_dir():
        sys.exit(f"{workspace} is not a directory")

    data = load(workspace)
    if args.dry_run:
        describe(data)
        return 0
    return export(workspace, data, fresh=args.fresh or "")


if __name__ == "__main__":
    raise SystemExit(main())
