"""Feature inventories: what an engine version has, derived mechanically from its own sources.

An inventory lists every keyword and every keyword-bearing grammar production of the engine's
parsers (from the Bison/Flex sources at the exact build commit) plus every entry of the official
reference index (names and links only). `inventory/<engine>/scope.yaml` classifies each item:
covered by a spec, planned, out of scope (with a reason) or open. `validate` fails on items that
no scope rule classifies, so nothing can be left out silently.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
import urllib.request
from pathlib import Path

import yaml

from .specs import ROOT, load_yaml

INVENTORY_DIR = ROOT / "inventory"
CACHE_DIR = ROOT / "dist" / "cache"

# parser id -> (grammar file, lexer file); error prefixes P01, P02, P03 ... name the parser
MANTICORE_PARSERS = {
    "sphinxql": ("src/sphinxql.y", "src/sphinxql.l"),
    "sphinxql_second": ("src/sphinxql_second.y", "src/sphinxql_second.l"),
    "sphinxql_extra": ("src/sphinxql_extra.y", "src/sphinxql_extra.l"),
    "sphinxql_debug": ("src/sphinxql_debug.y", "src/sphinxql_debug.l"),
    "ddl": ("src/ddl.y", "src/ddl.l"),
    "sphinxexpr": ("src/sphinxexpr.y", "src/sphinxexpr.l"),
    "sphinxquery": ("src/sphinxquery/sphinxquery.y", None),
}
MANTICORE_REPO = "manticoresoftware/manticoresearch"
MANTICORE_DOCS_INDEX = "manual/english/References.md"


# --- sources ---------------------------------------------------------------------------

def fetch(repo: str, commit: str, path: str) -> str:
    """Raw file at a commit, cached under dist/cache (read as text only, never executed)."""
    target = CACHE_DIR / repo.replace("/", "_") / commit / path
    if not target.exists():
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed https host
            data = resp.read()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target.read_text(encoding="utf-8", errors="replace")


def resolve_commit(repo: str, short: str) -> str:
    url = f"https://api.github.com/repos/{repo}/commits/{short}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        import json
        return json.load(resp)["sha"]


# --- Bison / Flex ----------------------------------------------------------------------

def _strip_c(text: str) -> str:
    """Remove C comments, string/char literals' braces stay intact for the action stripper."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _strip_actions(text: str) -> str:
    out, depth, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "'" and i + 2 < n and text[i + 2] == "'":  # char literal like '{' in the grammar
            if depth == 0:
                out.append(text[i:i + 3])
            i += 3
            continue
        if ch == '"' and depth > 0:  # string inside an action
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
        i += 1
    return "".join(out)


def parse_bison(text: str) -> dict[str, list[list[str]]]:
    """rule -> alternatives (token lists). Only the rules section between the first two %%."""
    parts = text.split("\n%%")
    body = parts[1] if len(parts) > 1 else text
    body = _strip_actions(_strip_c(body))
    body = re.sub(r"%prec\s+\S+|%empty", " ", body)
    rules: dict[str, list[list[str]]] = {}
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*:(.*?)(?:;\s*(?=[A-Za-z_][A-Za-z0-9_]*\s*:|$))", body + "\n", re.S):
        name, rhs = m.group(1), m.group(2)
        alts = [re.findall(r"'[^']'|'\\.'|[A-Za-z_][A-Za-z0-9_]*", alt) for alt in rhs.split("|")]
        rules.setdefault(name, []).extend(alts)
    return rules


def parse_flex_keywords(text: str) -> dict[str, str]:
    """TOK_X -> keyword text, from lexer lines like  "SELECT"  { ... return TOK_SELECT; }"""
    out = {}
    for m in re.finditer(r'^"([A-Za-z_][A-Za-z0-9_]*)"\s*\{[^\n]*?return\s+(TOK_[A-Z0-9_]+)', text, re.M):
        out.setdefault(m.group(2), m.group(1).upper())
    return out


def parse_bison_token_aliases(text: str) -> dict[str, str]:
    """%token TOK_X "alias" declarations (keyword aliases where the lexer is not keyword-driven)."""
    return {m.group(1): m.group(2) for m in re.finditer(r'%token\s+(?:<\w+>\s+)?(TOK_[A-Z0-9_]+)\s+"([^"]+)"', text)}


def _render(tokens: list[str], keywords: dict[str, str]) -> tuple[str, list[str]]:
    words, kws = [], []
    for t in tokens:
        if t in keywords:
            words.append(keywords[t])
            kws.append(keywords[t])
        elif t.startswith("'"):
            words.append(t.strip("'"))
        elif t.startswith("TOK_"):
            words.append(f"<{t[4:].lower()}>")
        else:
            words.append(f"<{t}>")
    return " ".join(words), kws


_KEYWORD_LIST_RULE = re.compile(r"ident|reserved_tokens|names_transaction")


def grammar_items(parser: str, grammar: str, lexer: str | None) -> list[dict]:
    keywords = parse_flex_keywords(lexer) if lexer else {}
    rules = parse_bison(grammar)
    items = []
    seen = set()
    for tok, kw in sorted(keywords.items(), key=lambda kv: kv[1]):
        if kw not in seen:
            seen.add(kw)
            items.append({"id": f"kw:{kw}", "kind": "keyword", "parser": parser})
    for rule, alts in rules.items():
        if _KEYWORD_LIST_RULE.search(rule):  # "these keywords may also be identifiers" lists
            continue
        for alt in alts:
            form, kws = _render(alt, keywords)
            punct = {t.strip("'") for t in alt if t.startswith("'")} - {",", ";"}
            # keyword forms, plus forms with syntax characters (j.a.b, cluster:table, name = (...)) and
            # operator tokens; pure sequences / list recursion of nonterminals are internal structure
            tokens = [t for t in alt if t.startswith("TOK_") and t not in keywords]
            if kws or punct or (tokens and len(alt) > 1 and not keywords):
                items.append({"id": f"{parser}:{rule}: {form}", "kind": "grammar", "parser": parser})
    return items


# --- reference index ---------------------------------------------------------------------

def docs_items(markdown: str, base_url: str) -> list[dict]:
    """Every '* [NAME](link)' entry with its section path (names and links only, no prose)."""
    items, path = [], []
    for line in markdown.splitlines():
        h = re.match(r"^(#+)\s*(.*)$", line)
        if h:
            level = len(h.group(1))
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h.group(2)).strip()
            path = [p for p in path if p[0] < level] + [(level, title)]
            continue
        m = re.match(r"^\s*\*\s*\[([^\]]+)\]\(([^)]+)\)", line)
        if m and path and not any("old Manticore versions" in t for _, t in path):
            section = " / ".join(t for _, t in path[1:]) or path[0][1]
            name = re.sub(r"%5B", "[", re.sub(r"%5D", "]", m.group(1))).strip()
            items.append({"id": f"docs:{section}: {name}", "kind": "docs",
                          "url": base_url + m.group(2)})
    return items


# --- generation ----------------------------------------------------------------------------

# manual pages whose headings are inventory items (OPTION names, functions, facet / highlight options)
MANTICORE_DOC_PAGES = [
    "manual/english/Searching/Options.md",
    "manual/english/Searching/Faceted_search.md",
    "manual/english/Searching/Highlighting.md",
    "manual/english/Searching/Conversational_search.md",
    "manual/english/Node_info_and_management/SHOW_QUERIES.md",
    "manual/english/Node_info_and_management/KILL.md",
    "manual/english/Functions/*.md",
]
BUDDY_REPO = "manticoresoftware/manticoresearch-buddy"


def _tree(repo: str, ref: str) -> list[str]:
    import json
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return [t["path"] for t in json.load(resp)["tree"]]


def page_items(markdown: str, page: str, base_url: str) -> list[dict]:
    """Headings (level 2+) of a manual page: one item per option / function / sub-feature."""
    items, in_code = [], False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{2,4})\s+(.+?)\s*$", line)
        if m:
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(2)).strip()
            rel = page.removeprefix("manual/english/").removesuffix(".md")
            items.append({"id": f"docs-page:{rel}: {title}", "kind": "docs", "url": base_url + rel})
    return items


def buddy_items(buddy_commit: str) -> tuple[list[dict], str | None]:
    """One item per Buddy plugin (statements the sidecar handles, outside the C++ grammar)."""
    try:
        ref = resolve_commit(BUDDY_REPO, buddy_commit)
        paths = _tree(BUDDY_REPO, ref)
    except Exception:  # noqa: BLE001 - tag missing: report no plugins rather than guessing
        return [], None
    plugins = sorted({p.split("/")[2] for p in paths if p.startswith("src/Plugin/") and p.count("/") >= 3})
    return [{"id": f"buddy:{name}", "kind": "plugin",
             "url": f"https://github.com/{BUDDY_REPO}/tree/{ref}/src/Plugin/{name}"} for name in plugins], ref


def generate_manticore(version: str, short_commit: str, buddy_commit: str | None = None) -> dict:
    commit = resolve_commit(MANTICORE_REPO, short_commit)
    items: list[dict] = []
    keyword_parsers: dict[str, list[str]] = {}
    for parser, (gfile, lfile) in MANTICORE_PARSERS.items():
        g = fetch(MANTICORE_REPO, commit, gfile)
        lx = fetch(MANTICORE_REPO, commit, lfile) if lfile else None
        for it in grammar_items(parser, g, lx):
            if it["kind"] == "keyword":
                keyword_parsers.setdefault(it["id"], []).append(parser)
            else:
                items.append(it)
    kw_items = [{"id": k, "kind": "keyword", "parsers": v} for k, v in sorted(keyword_parsers.items())]
    base = "https://manual.manticoresearch.com/"
    docs = docs_items(fetch(MANTICORE_REPO, commit, MANTICORE_DOCS_INDEX), base)
    tree = _tree(MANTICORE_REPO, commit)
    pages = sorted({p for pat in MANTICORE_DOC_PAGES for p in tree if fnmatch.fnmatchcase(p, pat)})
    for page in pages:
        docs += page_items(fetch(MANTICORE_REPO, commit, page), page, base)
    plugins, buddy_ref = buddy_items(buddy_commit) if buddy_commit else ([], None)
    unique = {}
    for it in kw_items + sorted(items, key=lambda i: i["id"]) + docs + plugins:
        unique.setdefault(it["id"], it)
    return {
        "engine": "manticore",
        "version": version,
        "generated_at": dt.date.today().isoformat(),
        "sources": [
            {"kind": "grammar", "repository": MANTICORE_REPO, "commit": commit,
             "files": [f for pair in MANTICORE_PARSERS.values() for f in pair if f]},
            {"kind": "docs-index", "repository": MANTICORE_REPO, "commit": commit, "files": [MANTICORE_DOCS_INDEX] + pages},
        ] + ([{"kind": "plugins", "repository": BUDDY_REPO, "commit": buddy_ref, "files": ["src/Plugin/*"]}] if buddy_ref else []),
        "notes": [
            "Statements handled by the Buddy sidecar (SHOW QUERIES, SHOW FULL TABLES, CREATE SOURCE / MATERIALIZED VIEW, the information_schema emulation, ...) are not in the C++ grammar: buddy: items name its plugins, the manual pages describe their statements.",
            "Function, OPTION and setting names are resolved in C++ tables, not by the grammar: docs-page: items (headings of the manual pages) are the source for them.",
            "Grammar items: alternatives with a keyword, a syntax character or (expression / full-text parsers, which have no keyword lexer) an operator token; plain sequences of nonterminals are internal structure.",
        ],
        "items": list(unique.values()),
    }


def write(doc: dict) -> Path:
    path = INVENTORY_DIR / doc["engine"] / f"{doc['version']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Generated by `uv run dbspecs inventory` from the engine's sources - do not edit.\n"
    path.write_text(header + yaml.safe_dump(doc, sort_keys=False, width=120, allow_unicode=True), encoding="utf-8")
    return path


# --- classification -------------------------------------------------------------------------

def stored() -> dict[str, dict[str, dict]]:
    """engine -> version -> inventory document"""
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(INVENTORY_DIR.glob("*/*.yaml")):
        doc = load_yaml(path)
        out.setdefault(doc["engine"], {})[doc["version"]] = doc
    return out


AUTO_KEYWORDS = {"match": ["kw:*"], "status": "covered", "specs": ["keywords:keyword-list"],
                 "reason": "listed in keywords/<engine>/<version>.yaml"}


def classify(inventory: dict, scope: dict | None, keyword_doc: dict | None) -> dict[str, dict | None]:
    """item id -> first matching scope rule (None = unclassified). Keywords contained in the
    engine's keyword file are covered without a rule."""
    rules = (scope or {}).get("rules", [])
    known = set((keyword_doc or {}).get("reserved", [])) | set((keyword_doc or {}).get("nonreserved", []))
    out = {}
    for it in inventory["items"]:
        rule = next((r for r in rules if any(fnmatch.fnmatchcase(it["id"], p) for p in r["match"])), None)
        if rule is None and it["kind"] == "keyword" and it["id"][3:] in known:
            rule = AUTO_KEYWORDS
        out[it["id"]] = rule
    return out


def spec_applies(specs, ref: str, engine: str) -> str | None:
    """None if <kind>:<id> exists and describes the engine, else the problem."""
    kind, _, sid = ref.partition(":")
    if kind == "keywords":
        return None
    if sid not in specs.docs.get(kind, {}):
        return f"unknown {kind} '{sid}'"
    doc = specs.get(kind, sid)
    present = {
        "syntax": lambda d: engine in d["grammars"] or engine in d.get("not_applicable", {}),
        "capability": lambda d: engine in d["support"],
        "operation": lambda d: engine in d["implementations"],
        "query": lambda d: any(v["engine"] == engine for v in d["variants"]) or engine in d.get("not_applicable", {}),
        "lexical": lambda d: specs.get("engine", engine)["lexical"] == sid,
        "engine": lambda d: sid == engine,
    }[kind]
    return None if present(doc) else f"{kind} '{sid}' says nothing about {engine}"
