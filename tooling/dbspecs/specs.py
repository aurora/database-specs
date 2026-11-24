"""Loading spec files, version ranges, templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# directory -> schema file; every *.yaml below the directory is validated against it
KINDS = {
    "engines": "engine",
    "protocols": "protocol",
    "lexical": "lexical",
    "capabilities": "capability",
    "operations": "operation",
    "queries": "query",
    "syntax": "syntax",
    "tests/cases": "test",
}


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps dates as strings (JSON has no date type)."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_Loader)


@dataclass
class Specs:
    root: Path
    docs: dict[str, dict[str, dict]] = field(default_factory=dict)  # kind -> id -> doc
    paths: dict[tuple[str, str], Path] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path = ROOT) -> "Specs":
        specs = cls(root)
        for directory, kind in KINDS.items():
            specs.docs[kind] = {}
            for path in sorted((root / directory).rglob("*.yaml")):
                doc = load_yaml(path)
                doc_id = doc.get("id") if isinstance(doc, dict) else None
                specs.docs[kind][doc_id or str(path)] = doc
                specs.paths[(kind, doc_id or str(path))] = path
        return specs

    def get(self, kind: str, doc_id: str) -> dict:
        return self.docs[kind][doc_id]

    def path(self, kind: str, doc_id: str) -> Path:
        return self.paths[(kind, doc_id)]


# --- versions ---------------------------------------------------------------

def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text))
    if not m:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(p) if p is not None else 0 for p in m.groups())


def in_range(version: str | tuple, entry: dict) -> bool:
    """since inclusive, until exclusive."""
    v = parse_version(version) if isinstance(version, str) else version
    if "since" in entry and v < parse_version(entry["since"]):
        return False
    if "until" in entry and v >= parse_version(entry["until"]):
        return False
    return True


def statement_for(statements: list[dict], version: str) -> dict | None:
    """Pick the versioned statement that applies (last match wins)."""
    found = None
    for st in statements:
        if in_range(version, st):
            found = st
    return found


def variant_for(query: dict, engine: str, version: str) -> dict | None:
    found = None
    for var in query["variants"]:
        if var["engine"] == engine and in_range(version, var):
            found = var
    return found


# --- templates --------------------------------------------------------------

_SECTION = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.S)
_VAR = re.compile(r"\{\{(\w+)\}\}")


def render(template: str, params: dict) -> str:
    """Mustache subset: {{name}}, {{#name}}...{{/name}} (if set), {{^name}}...{{/name}} (if not set)."""

    def section(m):
        is_set = params.get(m.group(2)) not in (None, "", False)
        return m.group(3) if is_set == (m.group(1) == "#") else ""

    out = _SECTION.sub(section, template)

    def var(m):
        name = m.group(1)
        if name not in params or params[name] is None:
            raise KeyError(f"template parameter missing: {name}")
        return str(params[name])

    return _VAR.sub(var, out)


def quote_identifier(lexical: dict, name: str) -> str:
    """Quote with the dialect's preferred identifier quote."""
    pref = lexical["identifiers"].get("preferred_quote")
    for q in lexical["identifiers"]["quotes"]:
        if q["open"] == pref and "when" not in q and "prefix" not in q:
            close = q["close"]
            escaped = name.replace(close, close + close) if "double" in q.get("escape", []) else name
            return f"{q['open']}{escaped}{close}"
    raise ValueError(f"no unconditional preferred quote in lexical spec {lexical['id']}")
