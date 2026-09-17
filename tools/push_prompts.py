#!/usr/bin/env python3
"""Upload the agents' prompts to Langfuse Prompt Management.

The eight prompts live in `.claude/skills/<agent>/SKILL.md`. This pushes them
to Langfuse, where they can be edited, versioned and labelled without a commit
and a deploy — which is the reason for moving them.

**What does not move.** Role, model and `writes_bible` stay in the front matter
and are cross-checked against `specs/flow.yaml` and the code. Authority is a
repository fact; a prompt service supplies wording. A Langfuse project that
could grant Bible access by editing a prompt would make SEC-4.3 a suggestion,
so `novaforge/prompts.py` reads only the text.

After this, `.claude/skills/` keeps two jobs: it is the fallback when Langfuse
is unreachable, and it is what `tools/check_specs.py` reads to trace the 40
declared requirements.

    python tools/push_prompts.py            # what would be pushed
    python tools/push_prompts.py --push     # actually push
    python tools/push_prompts.py --push --label staging
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novaforge.agents import load_agents  # noqa: E402
from novaforge.prompts import langfuse_host  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--push", action="store_true",
                        help="upload; without it this only reports what would go")
    parser.add_argument("--label", default="production",
                        help="the label to attach (default: production)")
    args = parser.parse_args(argv)

    agents = load_agents(ROOT)
    print(f"{len(agents)} prompts in .claude/skills/\n")
    for agent in agents:
        slots = ", ".join(sorted(agent.placeholders)) or "none"
        shipping = "" if agent.on_shipping_path else "  [off the shipping path]"
        print(f"  novaforge/{agent.name:<20} {len(agent.prompt):>5} chars  "
              f"slots: {slots}{shipping}")

    if not args.push:
        print("\nNothing was uploaded. Add --push to send them.")
        return 0

    if not (os.environ.get("LANGFUSE_PUBLIC_KEY")
            and os.environ.get("LANGFUSE_SECRET_KEY")):
        print("\nLANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set.",
              file=sys.stderr)
        return 2
    try:
        from langfuse import Langfuse
    except ImportError:
        print("\npip install 'novaforge[langfuse]'", file=sys.stderr)
        return 2

    client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=langfuse_host(),
    )
    if not client.auth_check():
        print("\nthose credentials do not reach a project", file=sys.stderr)
        return 1

    print(f"\npushing with label {args.label!r}:")
    failed = 0
    for agent in agents:
        try:
            client.create_prompt(
                name=f"novaforge/{agent.name}",
                prompt=agent.prompt,
                type="text",
                labels=[args.label],
                tags=["novaforge", f"role:{agent.role}",
                      "shipping" if agent.on_shipping_path else "parked"],
                # Wording only. Role and writes_bible are not sent, because
                # nothing here is allowed to become the authority for them.
                config={"spec": agent.spec_path,
                        "placeholders": sorted(agent.placeholders)},
            )
            print(f"  ok    novaforge/{agent.name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  novaforge/{agent.name}: {type(exc).__name__}: {exc}")
    client.flush()

    if failed:
        print(f"\n{failed} of {len(agents)} failed")
        return 1
    print(f"\n{len(agents)} prompts pushed. Runs with "
          f"agents.prompt_source = 'langfuse' will use them; the SKILL.md files "
          f"stay as the fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
