"""The numbers the documentation quotes, checked against the real ones.

Every document here quotes output: a test count, a chain length, the line the
publish stage prints. Each of those drifts the moment the code changes, and a
README that confidently states the wrong byte count is the same kind of problem
as a spec requirement nobody tests — it is a claim with nothing behind it.

This has already drifted three times in this project's short history: the test
count after each new suite, the chain length when `gate_decision` rows were
added, and the PDF's size when the mock stopped repeating itself. Each time it
was caught by reading rather than by running, which is the part worth fixing.

`specs/acceptance.md` is not covered here; its criteria have their own tests in
`tests/test_acceptance.py`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from novaforge.config import package_root

ROOT = package_root()
GOLDEN = ROOT / "output" / "golden-tiny"

pytestmark = pytest.mark.skipif(
    not (GOLDEN / "state.json").exists(),
    reason="golden-tiny has not been generated",
)


def prose(name: str) -> str:
    """A document read as prose: unwrapped, and without blockquote markers.

    These files are hard-wrapped, so a sentence is usually split across lines,
    and inside a blockquote each of those lines starts with a `> ` that would
    otherwise land in the middle of it.
    """
    raw = (ROOT / name).read_text(encoding="utf-8")
    return " ".join(re.sub(r"(?m)^\s*>\s?", "", raw).split())


@pytest.fixture(scope="module")
def facts():
    """What is actually true right now."""
    state = json.loads((GOLDEN / "state.json").read_text(encoding="utf-8"))
    log = (GOLDEN / "logs" / "agents.jsonl").read_text(encoding="utf-8")
    pdf = (GOLDEN / "dist" / "book.pdf").read_bytes()
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=str(ROOT)).stdout
    return {
        "tests": int(re.search(r"(\d+) tests? collected", collected).group(1)),
        "rows": len([line for line in log.splitlines() if line.strip()]),
        "calls": state["calls"],
        "chapters": len(state["chapters"]),
        "pdf_bytes": len(pdf),
        "pdf_pages": len(re.findall(rb"/Type /Page[^s]", pdf)),
    }


class TestQuotedNumbers:
    def test_the_readme_quotes_the_real_test_count(self, facts):
        assert f"# {facts['tests']} tests" in prose("README.md")

    @pytest.mark.parametrize("name", ["README.md", "RUNBOOK.md",
                                      "output/golden-tiny/README.md"])
    def test_every_quoted_chain_length_is_the_real_one(self, facts, name):
        quoted = [int(n) for n in re.findall(r"chain intact \((\d+) rows", prose(name))]
        assert quoted, f"{name} quotes no chain length"
        assert all(n == facts["rows"] for n in quoted), quoted

    @pytest.mark.parametrize("name", ["README.md", "RUNBOOK.md"])
    def test_the_quoted_publish_line_matches_what_the_stage_prints(self, facts, name):
        """The line most likely to drift, because it carries a byte count."""
        found = re.findall(
            r"wrote dist/book\.pdf — (\d+) pages, A5, [\d.]+pt Helvetica, ([\d,]+) bytes",
            prose(name))
        assert found, f"{name} does not quote the PDF line"
        for pages, size in found:
            assert int(pages) == facts["pdf_pages"]
            assert int(size.replace(",", "")) == facts["pdf_bytes"]

    def test_the_runbook_quotes_the_real_call_count(self, facts):
        quoted = re.search(r"calls\s+(\d+)\s+\(", prose("RUNBOOK.md"))
        assert quoted and int(quoted.group(1)) == facts["calls"]


class TestClaimsThatHaveExpiredBefore:
    """Each of these was true once and had to be corrected. Pinned so that the
    correction does not have to happen a second time."""

    def test_the_runbook_does_not_say_its_commands_were_never_run(self):
        assert "None of the commands below have been executed" not in prose("RUNBOOK.md")

    def test_the_runbook_does_not_say_nothing_has_been_pushed(self):
        text = prose("RUNBOOK.md")
        assert "Nothing has been pushed" not in text
        assert "no remote configured yet" not in text

    def test_the_fixture_readme_does_not_say_it_is_empty(self):
        text = prose("output/golden-tiny/README.md")
        assert "NOT YET GENERATED" not in text
        assert "It is empty" not in text

    def test_security_marks_no_layer_as_unwritten(self):
        assert "NOT YET WRITTEN" not in prose("SECURITY.md")


class TestTheLimitationsAreStated:
    @pytest.mark.parametrize("name,needle", [
        ("README.md", "ignores your premise"),
        ("RUNBOOK.md", "premise does not reach the prose"),
        ("output/golden-tiny/README.md", "nothing to do with the premise"),
    ])
    def test_the_mock_limitation_is_said_where_it_is_read(self, name, needle):
        assert needle in prose(name), name

    def test_the_readme_says_the_anthropic_engine_is_missing(self):
        assert "`--engine anthropic` is not implemented" in prose("README.md")


class TestEveryReferencedFileExists:
    """A document citing a file that is not there is how `specs/acceptance.md`
    and `tools/publish.ps1` stayed missing for so long: referenced confidently
    from several places, and never checked."""

    PATTERN = re.compile(
        r"`((?:novaforge|tests|specs|tools|config|docs|output)/[A-Za-z0-9_./-]+"
        r"|(?:README|RUNBOOK|SECURITY)\.md)`")

    # Cited as not existing, on purpose.
    DECLARED_ABSENT = {"novaforge/engines/anthropic.py"}

    @pytest.mark.parametrize("name", [
        "README.md", "RUNBOOK.md", "SECURITY.md",
        "specs/acceptance.md", "specs/CONFIG-SPEC.md",
    ])
    def test_every_path_a_document_cites_resolves(self, name):
        missing = []
        for match in self.PATTERN.findall((ROOT / name).read_text(encoding="utf-8")):
            if any(ch in match for ch in "*{<") or match in self.DECLARED_ABSENT:
                continue
            if not (ROOT / match).exists():
                missing.append(match)
        assert missing == [], f"{name} cites: {missing}"
