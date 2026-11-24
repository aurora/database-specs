"""Bundle all specs into one JSON file for consumers."""

from __future__ import annotations

import json
from pathlib import Path

from .diagrams import render_all
from .specs import Specs
from .syntax import grammar_path

FORMAT_VERSION = 1


def build(specs: Specs, out: Path, verification: Path | None = None) -> Path:
    queries = {}
    for doc_id, q in specs.docs["query"].items():
        q = json.loads(json.dumps(q))  # deep copy
        base = specs.path("query", doc_id).parent
        for var in q["variants"]:
            var["sql"] = (base / var["file"]).read_text(encoding="utf-8")
        queries[doc_id] = q

    syntax = {}
    for doc_id, syn in specs.docs["syntax"].items():
        syn = json.loads(json.dumps(syn))
        for eid, g in syn["grammars"].items():
            g["ebnf"] = grammar_path(specs, doc_id, eid).read_text(encoding="utf-8")
        syntax[doc_id] = syn

    bundle = {
        "format_version": FORMAT_VERSION,
        "engines": specs.docs["engine"],
        "protocols": specs.docs["protocol"],
        "lexical": specs.docs["lexical"],
        "capabilities": specs.docs["capability"],
        "operations": specs.docs["operation"],
        "queries": queries,
        "syntax": syntax,
        "keywords": {kw["engine"]: {} for kw in specs.docs["keywords"].values()},
    }
    for kw in specs.docs["keywords"].values():
        bundle["keywords"][kw["engine"]][kw["version"]] = kw
    if verification and verification.is_file():
        bundle["verification"] = json.loads(verification.read_text(encoding="utf-8"))

    out.parent.mkdir(parents=True, exist_ok=True)
    render_all(specs, out.parent / "syntax")
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return out
