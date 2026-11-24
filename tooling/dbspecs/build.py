"""Bundle all specs into one JSON file for consumers."""

from __future__ import annotations

import json
from pathlib import Path

from .specs import Specs

FORMAT_VERSION = 1


def build(specs: Specs, out: Path, verification: Path | None = None) -> Path:
    queries = {}
    for doc_id, q in specs.docs["query"].items():
        q = json.loads(json.dumps(q))  # deep copy
        base = specs.path("query", doc_id).parent
        for var in q["variants"]:
            var["sql"] = (base / var["file"]).read_text(encoding="utf-8")
        queries[doc_id] = q

    bundle = {
        "format_version": FORMAT_VERSION,
        "engines": specs.docs["engine"],
        "protocols": specs.docs["protocol"],
        "lexical": specs.docs["lexical"],
        "capabilities": specs.docs["capability"],
        "operations": specs.docs["operation"],
        "queries": queries,
    }
    if verification and verification.is_file():
        bundle["verification"] = json.loads(verification.read_text(encoding="utf-8"))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return out
