"""One-off: put token counts into the run that predates the orchestrator recording them.

The `deep-space-salvage-derelict` run was driven before `SKILL.md` said to log
`tokens`, so its log has none and the Langfuse export went up with no usage at
all. The numbers do exist — Claude Code reported `subagent_tokens` on every
Agent result and every task notification in that session — so this transcribes
them onto the rows they belong to.

**Every row it writes is marked `"tokens_source": "reconstructed"`.** A figure
copied out of a transcript is not the same kind of fact as one the orchestrator
recorded as it happened, and a reader should not have to know which run this
was to tell them apart.

Two properties of `subagent_tokens` that the export has to state rather than
paper over:

* **It is a total.** There is no input/output split, so cost can be bounded but
  not computed. See `config/pricing.json`.
* **It is cumulative across a resume.** An agent that was sent back for a
  redraft reports the running total for the whole agent, not the cost of the
  second attempt, so the per-attempt figures below are differences.

This script is safe to re-run: it rewrites `tokens` on matched rows rather than
appending, and leaves everything else in the row untouched.

    python tools/backfill_tokens.py output/deep-space-salvage-derelict
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Which model each agent runs on, from the `model:` front matter in
# .claude/agents/<name>.md. Kept here rather than re-parsed, and checked against
# those files by the assertion in `main()` so the two cannot drift silently.
MODELS = {
    "worldbuilder": "claude-opus-5",
    "character-architect": "claude-opus-5",
    "plot-architect": "claude-opus-5",
    "chapter-writer": "claude-opus-5",
    "continuity-critic": "claude-sonnet-5",
    "science-critic": "claude-sonnet-5",
    "style-editor": "claude-sonnet-5",
    "publisher": "claude-sonnet-5",
}

# (agent, chapter, iteration) -> tokens for THAT attempt.
#
# Where a figure is a difference, the arithmetic is shown. The worldbuilder ran
# three times: once to write, once on a trim that the Write tool refused because
# the agent had no Read tool, and once to write the trimmed text after the file
# was deleted. The middle one produced nothing and cost 17,479 tokens, which is
# the price of that design defect and is left visible rather than folded away.
TOKENS = {
    ("worldbuilder", None, 1): 8586,
    ("worldbuilder", None, 2): 17479,   # 26065 - 8586, the blocked rewrite
    ("worldbuilder", None, 3): 2673,    # 28738 - 26065
    ("character-architect", None, 1): 13099,
    ("plot-architect", None, 1): 13112,

    ("chapter-writer", 1, 1): 10603,
    ("continuity-critic", 1, 1): 10841,
    ("science-critic", 1, 1): 12771,

    ("chapter-writer", 2, 1): 11243,
    ("continuity-critic", 2, 1): 17309,
    ("science-critic", 2, 1): 16232,
    ("chapter-writer", 2, 2): 3665,     # 14908 - 11243, the repair
    ("continuity-critic", 2, 2): 14260,
    ("science-critic", 2, 2): 13493,

    ("chapter-writer", 3, 1): 13397,
    ("continuity-critic", 3, 1): 20668,
    ("science-critic", 3, 1): 17675,
    ("chapter-writer", 3, 2): 2221,     # 15618 - 13397, the one-clause repair
    ("continuity-critic", 3, 2): 13255,
    ("science-critic", 3, 2): 7681,     # the re-score of the shipped draft

    ("style-editor", 1, None): 8463,
    ("style-editor", 2, None): 8441,
    ("style-editor", 3, None): 8511,

    ("publisher", None, None): 15524,
}


def key(row: dict) -> tuple:
    return (row.get("agent"), row.get("chapter"), row.get("iteration"))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    workspace = Path(argv[1])
    log = workspace / "logs" / "agents.jsonl"
    if not log.exists():
        sys.exit(f"no run log at {log}")

    # Front matter is the authority on which model an agent runs; this table is
    # a copy, so prove the copy is current before writing anything with it.
    agents_dir = Path(".claude/agents")
    if agents_dir.is_dir():
        for name, expected in MODELS.items():
            path = agents_dir / f"{name}.md"
            if not path.exists():
                continue
            declared = ""
            for line in path.read_text(encoding="utf-8").splitlines()[:12]:
                if line.startswith("model:"):
                    declared = line.split(":", 1)[1].strip()
                    break
            short = expected.replace("claude-", "").split("-")[0]
            if declared and declared != short:
                sys.exit(f"{path} declares model '{declared}' but this script "
                         f"assumes '{short}'. Fix one of them.")

    rows = [json.loads(line) for line in
            log.read_text(encoding="utf-8").splitlines() if line.strip()]

    matched = unmatched = 0
    for row in rows:
        if not row.get("agent"):
            continue
        tokens = TOKENS.get(key(row))
        if tokens is None:
            unmatched += 1
            print(f"  no token figure for {key(row)}")
            continue
        row["tokens"] = tokens
        row["tokens_source"] = "reconstructed"
        row["model"] = MODELS.get(row["agent"], "unknown")
        matched += 1

    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    total = sum(r.get("tokens", 0) for r in rows)
    print(f"{matched} rows given token counts, {unmatched} left without")
    print(f"total across the run: {total:,} tokens")

    by_agent: dict[str, int] = {}
    for row in rows:
        if row.get("tokens"):
            by_agent[row["agent"]] = by_agent.get(row["agent"], 0) + row["tokens"]
    print()
    for agent, n in sorted(by_agent.items(), key=lambda kv: -kv[1]):
        print(f"  {agent:<22}{n:>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
