# CHG-001 — Remove the EPUB and the SVG cover

> **On the `claude-orchestrator` branch, read this as history.** It records
> something that happened to the Python implementation, which lives on `main`.
> The files it names are not in this branch's tree. See CHG-003.

**Status:** done, before this repository had a working shell.

## What changed

`outputs.formats` dropped `epub`, and the SVG cover generator was removed. The
manuscript ships as Markdown and PDF.

## Why

An EPUB is a zip of XHTML, and a cover is an SVG. Both are XML formats, which
means both need correct escaping of model-written text, and neither was being
exercised by anything a reader would look at. Two formats that nobody opened
were carrying the risk of two escapers nobody had reason to trust.

## What it left behind

`xml_escape` and `svg_text` in `novaforge/security/escaping.py`. They are on no
code path and are tested anyway.

That combination is deliberate and worth stating, because it looks like dead
code and is not. `SECURITY.md` puts it as: an untested escaper is worse than
none, and these are the correct tool the moment an XML format returns. Deleting
them would mean rewriting them under pressure later; leaving them untested
would mean trusting them without evidence.

`tests/security/test_sec5_escaping.py::TestOffTheShippingPath::test_they_really_are_unused`
asserts that nothing calls them. When that test fails, an XML format has come
back and this change record needs updating.

## Traces

- `novaforge/security/escaping.py` — the two functions and why they stay
- `SECURITY.md` § SEC-5
- `config/novel.config.json` — `outputs.formats` is `["markdown", "pdf"]`
