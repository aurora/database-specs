"""Schema validation and cross-reference checks."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .specs import KINDS, Specs

BASE = "https://db-specs.invalid/schemas/"


def _registry(root: Path) -> tuple[Registry, dict[str, dict]]:
    schemas = {}
    resources = []
    for path in sorted((root / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name.removesuffix(".schema.json")] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources), schemas


def validate(specs: Specs) -> list[str]:
    errors: list[str] = []
    registry, schemas = _registry(specs.root)

    # 1. JSON schema
    for directory, kind in KINDS.items():
        validator = Draft202012Validator(schemas[kind], registry=registry, format_checker=FormatChecker())
        for doc_id, doc in specs.docs[kind].items():
            rel = specs.path(kind, doc_id).relative_to(specs.root)
            for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
                loc = "/".join(str(p) for p in err.path) or "<root>"
                errors.append(f"{rel}: {loc}: {err.message}")

    if errors:
        return errors  # cross refs assume valid structure

    # 2. ids unique per kind and matching the file location
    for kind in ("capability", "operation", "query"):
        for doc_id in specs.docs[kind]:
            path = specs.path(kind, doc_id)
            rel = path.relative_to(specs.root)
            expected = ".".join(rel.with_suffix("").parts[1:]) if kind != "query" else ".".join(rel.parent.parts[1:])
            if doc_id != expected:
                errors.append(f"{rel}: id '{doc_id}' should be '{expected}' (derived from path)")
    for kind in ("engine", "protocol", "lexical"):
        for doc_id in specs.docs[kind]:
            path = specs.path(kind, doc_id)
            if path.stem != doc_id:
                errors.append(f"{path.relative_to(specs.root)}: id '{doc_id}' should match file name")

    engines = specs.docs["engine"]

    def check_engine(rel, eid):
        if eid not in engines:
            errors.append(f"{rel}: unknown engine '{eid}'")

    # 3. cross references
    for eid, eng in engines.items():
        rel = specs.path("engine", eid).relative_to(specs.root)
        for p in eng["protocols"]:
            if p not in specs.docs["protocol"]:
                errors.append(f"{rel}: unknown protocol '{p}'")
        if eng["lexical"] not in specs.docs["lexical"]:
            errors.append(f"{rel}: unknown lexical spec '{eng['lexical']}'")
        if "extends" in eng:
            check_engine(rel, eng["extends"].split("@")[0])

    for kind, key in (("capability", "support"), ("operation", "implementations")):
        for doc_id, doc in specs.docs[kind].items():
            rel = specs.path(kind, doc_id).relative_to(specs.root)
            for eid in doc[key]:
                check_engine(rel, eid)
            for probe in doc.get("probes", []):
                for eid in probe["engines"]:
                    check_engine(rel, eid)
            for r in doc.get("related", []):
                if r not in specs.docs[kind]:
                    errors.append(f"{rel}: related '{r}' not found")

    for doc_id, q in specs.docs["query"].items():
        path = specs.path("query", doc_id)
        rel = path.relative_to(specs.root)
        for var in q["variants"]:
            check_engine(rel, var["engine"])
            if not (path.parent / var["file"]).is_file():
                errors.append(f"{rel}: variant file '{var['file']}' missing")

    for doc_id, t in specs.docs["test"].items():
        rel = specs.path("test", doc_id).relative_to(specs.root)
        for eid in t["engines"]:
            check_engine(rel, eid)
        for step in t["steps"]:
            if "query" in step and step["query"] not in specs.docs["query"]:
                errors.append(f"{rel}: unknown query '{step['query']}'")
            if "operation" in step and step["operation"] not in specs.docs["operation"]:
                errors.append(f"{rel}: unknown operation '{step['operation']}'")

    return errors
