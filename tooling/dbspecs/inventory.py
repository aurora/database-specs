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
    # rule headers start a line; the closing ';' is optional in Bison (MySQL omits it)
    heads = list(re.finditer(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*:(?!:)", body, re.M))
    for k, m in enumerate(heads):
        name = m.group(1)
        rhs = body[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(body)]
        rhs = re.sub(r";\s*$", "", rhs.rstrip())
        # tokenize first, then split on bare '|' (a quoted '|' is the bitwise / full-text OR token)
        tokens = re.findall(r"'[^']'|'\\.'|[A-Za-z_][A-Za-z0-9_]*|\|", rhs)
        alts, cur = [], []
        for t in tokens:
            if t == "|":
                alts.append(cur)
                cur = []
            else:
                cur.append(t)
        alts.append(cur)
        rules.setdefault(name, []).extend(alts)
    return rules


def parse_flex_keywords(text: str) -> dict[str, str]:
    """TOK_X -> keyword text, from lexer lines like  "SELECT"  { ... return TOK_SELECT; }"""
    out = {}
    # "SELECT" { ... return TOK_SELECT; }  and multi-word tokens like  "MODIFY"[ \t\n\r]+"COLUMN"
    word = r'"[A-Za-z_][A-Za-z0-9_]*"'
    for m in re.finditer(rf'^({word}(?:(?:\[[^\]]*\]\+|\{{SPACE\}}\+){word})*)\s*\{{[^\n]*?return\s+(TOK_[A-Z0-9_]+)',
                         text, re.M):
        words = re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1))
        out.setdefault(m.group(2), " ".join(w.upper() for w in words))
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
        elif t in SIGIL_TOKENS:
            words.append(SIGIL_TOKENS[t])
        elif t.startswith("TOK_"):
            words.append(f"<{t[4:].lower()}>")
        else:
            words.append(f"<{t}>")
    return " ".join(words), kws


def _is_keyword_list(alts: list[list[str]], keywords: dict[str, str]) -> bool:
    """Rules like 'these keywords may also be identifiers': every alternative is one keyword token,
    at least one is a plain identifier token or the list is long (reserved_tokens ...)."""
    singles = [a for a in alts if len(a) == 1 and a[0] in keywords]
    others = [a for a in alts if not (len(a) == 1 and a[0] in keywords)]
    if not singles or not all(len(a) == 1 and not a[0].startswith("'") for a in others):
        return False
    # an identifier alternative (TOK_IDENT, another ident rule) next to keywords, or a very long list
    return (bool(others) and len(singles) >= 6) or len(singles) >= 30


def grammar_items(parser: str, grammar: str, lexer: str | None, keywords: dict[str, str] | None = None) -> list[dict]:
    """keywords: TOKEN -> text when the engine has no Flex lexer (MySQL: sql/lex.h)."""
    keywords = keywords if keywords is not None else (parse_flex_keywords(lexer) if lexer else {})
    rules = parse_bison(grammar)
    items = []
    seen = set()
    for tok, kw in sorted(keywords.items(), key=lambda kv: kv[1]):
        for word in kw.split():  # multi-word tokens (MODIFY COLUMN) are made of keywords
            if word not in seen:
                seen.add(word)
                items.append({"id": f"kw:{word}", "kind": "keyword", "parser": parser})
    # rules that only spell keywords (describe_command: DESC | DESCRIBE): an alternative starting with
    # one is a statement of its own even without a keyword of its own (describe_stmt, explain_stmt)
    keyword_rules = {r for r, alts in rules.items()
                     if alts and all(a and all(t in keywords for t in a) for a in alts)}
    for rule, alts in rules.items():
        if _is_keyword_list(alts, keywords):  # "these keywords may also be identifiers" lists
            continue
        for alt in alts:
            form, kws = _render(alt, keywords)
            punct = {t.strip("'") for t in alt if t.startswith("'")} - {",", ";"}
            # keyword forms, plus forms with syntax characters (j.a.b, cluster:table, name = (...)) and
            # operator tokens; pure sequences / list recursion of nonterminals are internal structure
            tokens = [t for t in alt if t.startswith("TOK_") and t not in keywords]
            sigil = any(t in SIGIL_TOKENS for t in alt)
            lead = len(alt) > 1 and alt[0] in keyword_rules
            if kws or punct or sigil or lead or (tokens and len(alt) > 1 and not keywords):
                items.append({"id": f"{parser}:{rule}: {form}", "kind": "grammar", "parser": parser})
    # names the actions compare an identifier with (ALGORITHM = INSTANT, FORMAT = TREE): words of the
    # language that the grammar itself reads as <ident>
    for rule, names in identifier_values(grammar).items():
        for name in names:
            items.append({"id": f"{parser}:{rule}: {name} (name)", "kind": "grammar", "parser": parser})
    return items


def identifier_values(grammar: str) -> dict[str, list[str]]:
    """rule -> names checked with is_identifier($n, "NAME") in its actions (MySQL)."""
    parts = grammar.split("\n%%")
    body = _strip_c(parts[1] if len(parts) > 1 else grammar)
    heads = list(re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*:(?!:)", body, re.M))
    out: dict[str, list[str]] = {}
    for k, m in enumerate(heads):
        chunk = body[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(body)]
        names = re.findall(r'is_identifier\(\s*\$\d+\s*,\s*"([A-Za-z_][A-Za-z0-9_]*)"', chunk)
        if names:
            out.setdefault(m.group(1), [])
            out[m.group(1)] += [n for n in dict.fromkeys(names) if n not in out[m.group(1)]]
    return out


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
    # option / parameter names live on these pages (not in the grammar, not in the reference index)
    "manual/english/Searching/Spell_correction.md",
    "manual/english/Searching/Autocomplete.md",
    "manual/english/Searching/KNN.md",
    "manual/english/Searching/Joining.md",
    "manual/english/Searching/Percolate_query.md",
    "manual/english/Searching/Sorting_and_ranking.md",
    "manual/english/Listing_tables.md",
    "manual/english/Creating_a_table/Data_types.md",
    "manual/english/Data_creation_and_modification/Updating_documents/UPDATE.md",
    # session / global variable names, MATCH() escaping, grouping forms, scroll pagination
    "manual/english/Server_settings/Setting_variables_online.md",
    "manual/english/Searching/Full_text_matching/Escaping.md",
    "manual/english/Searching/Grouping.md",
    "manual/english/Searching/Pagination.md",
]
# built-in expression functions: table g_dFuncs, names in comments  { /*"now", */ 0, TOK_FUNC, ...
MANTICORE_FUNC_TABLE = "src/sphinxexpr.cpp"
# tokens that stand for sigil syntax (@@session.x, @var) rather than identifiers
SIGIL_TOKENS = {"TOK_SYSVAR": "@@<sysvar>", "TOK_USERVAR": "@<uservar>"}
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
        m = None if in_code else re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if m:
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(2)).strip()
            rel = page.removeprefix("manual/english/").removesuffix(".md")
            items.append({"id": f"docs-page:{rel}: {title}", "kind": "docs", "url": base_url + rel})
    return items


def function_items(source: str, base_url: str, table: str = "g_dFuncs", source_file: str | None = None) -> list[dict]:
    """Names of the built-in functions from a C++ function table (Manticore g_dFuncs: names in
    comments, the grammar only has TOK_FUNC; MySQL func_array: {"ABS", ...})."""
    start = source.find(table + "[")
    end = source.find("};", start)
    names = re.findall(r'"(\w+)"', source[start:end]) if start >= 0 else []
    return [{"id": f"func:{n.upper()}", "kind": "function",
             "url": base_url + (source_file or MANTICORE_FUNC_TABLE)} for n in dict.fromkeys(names)]


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
    funcs = function_items(fetch(MANTICORE_REPO, commit, MANTICORE_FUNC_TABLE),
                           f"https://github.com/{MANTICORE_REPO}/blob/{commit}/")
    plugins, buddy_ref = buddy_items(buddy_commit) if buddy_commit else ([], None)
    unique = {}
    for it in kw_items + sorted(items, key=lambda i: i["id"]) + funcs + docs + plugins:
        unique.setdefault(it["id"], it)
    return {
        "engine": "manticore",
        "version": version,
        "generated_at": dt.date.today().isoformat(),
        "sources": [
            {"kind": "grammar", "repository": MANTICORE_REPO, "commit": commit,
             "files": [f for pair in MANTICORE_PARSERS.values() for f in pair if f] + [MANTICORE_FUNC_TABLE]},
            {"kind": "docs-index", "repository": MANTICORE_REPO, "commit": commit, "files": [MANTICORE_DOCS_INDEX] + pages},
        ] + ([{"kind": "plugins", "repository": BUDDY_REPO, "commit": buddy_ref, "files": ["src/Plugin/*"]}] if buddy_ref else []),
        "notes": [
            "Statements handled by the Buddy sidecar (SHOW QUERIES, SHOW FULL TABLES, CREATE SOURCE / MATERIALIZED VIEW, the information_schema emulation, ...) are not in the C++ grammar: buddy: items name its plugins, the manual pages describe their statements.",
            "Function names come from the C++ function table (func: items). OPTION and setting names are resolved in C++ tables too: docs-page: items (headings of the manual pages) are the source for them. Names that the pages only list inside text or tables (most OPTION names, CALL SUGGEST / AUTOCOMPLETE / KEYWORDS / PQ options, knn() options, ranker names and ranking factors) are not separate items - the specs for them (dml.select, dml.call) must take them from the pages.",
            "Grammar items: alternatives with a keyword, a syntax character or (expression / full-text parsers, which have no keyword lexer) an operator token; plain sequences of nonterminals are internal structure.",
        ],
        "items": list(unique.values()),
    }


MYSQL_REPO = "mysql/mysql-server"
# parser id -> grammar file; keywords come from sql/lex.h (no Flex lexer)
MYSQL_PARSERS = {"sql": "sql/sql_yacc.yy", "hints": "sql/sql_hints.yy"}
MYSQL_KEYWORDS = "sql/lex.h"
MYSQL_FUNC_TABLE = "sql/item_create.cc"


def parse_lex_h(text: str) -> dict[str, tuple[str, str | None]]:
    """TOKEN -> (keyword text, group) from sql/lex.h: SYM = keyword, SYM_HK = keyword that may start
    an optimizer hint, SYM_FN = function-like word (group "function"), SYM_H = hint-only word
    (group "hint"). 5.6 writes { "ADD", SYM(ADD)}; there function words are in a separate sql_functions[]."""
    groups = {"_FN": "function", "_H": "hint", "_HK": None, "": None}
    out = {}
    for m in re.finditer(r'SYM(_FN|_HK|_H)?\(\s*"([^"]+)"\s*,\s*([A-Za-z0-9_]+)\s*\)', text):
        out.setdefault(m.group(3), (m.group(2), groups[m.group(1) or ""]))
    funcs_at = text.find("sql_functions[]")
    for m in re.finditer(r'\{\s*"([^"]+)"\s*,\s*SYM(_FN|_HK|_H)?\(\s*([A-Za-z0-9_]+)', text):
        group = "function" if 0 <= funcs_at < m.start() else groups[m.group(2) or ""]
        out.setdefault(m.group(3), (m.group(1), group))
    return out


HELP_CATEGORIES_SQL = "SELECT help_category_id, name, parent_category_id FROM mysql.help_category"
HELP_TOPICS_SQL = "SELECT help_category_id, name, url FROM mysql.help_topic ORDER BY help_topic_id"


def help_items(categories: list[tuple], topics: list[tuple]) -> list[dict]:
    """Topic names of the server's HELP tables (generated from the reference manual):
    help:<category path>: <topic>. Only names, categories and links are read - never the help text."""
    cats = {int(cid): (name, int(parent)) for cid, name, parent in categories}
    topics = [(int(cid), name, url) for cid, name, url in topics]

    def path(cid):
        name, parent = cats[cid]
        if cid == parent or parent not in cats or cats[parent][0] == "Contents":
            return name
        return f"{path(parent)} / {name}"

    items = []
    for cid, name, url in topics:
        if cats.get(cid, ("",))[0] == "Help Metadata":
            continue
        name = re.sub(r"\\([_*\\\[\]])", r"\1", name).strip()  # MariaDB's KB export escapes markdown: AES\_DECRYPT
        items.append({"id": f"help:{path(cid)}: {name}", "kind": "docs", **({"url": url} if url else {})})
    return items


PRIVILEGES_SQL = "SHOW PRIVILEGES"


def preprocess_bison_ifdef(text: str, keep: str = "MARIADB") -> str:
    """MariaDB's sql_yacc.yy holds both grammars: %ifdef MARIADB ... %else ... %endif ORACLE. The build
    generates sql_yacc.yy (default mode) and sql_yacc_ora.yy from it; keep the default branch."""
    out, stack = [], []
    for line in text.splitlines(keepends=True):
        m = re.match(r"^%(ifdef|else|endif)\b\s*(\w*)", line)
        if m:
            if m.group(1) == "ifdef":
                stack.append(m.group(2) == keep)
            elif m.group(1) == "else" and stack:
                stack[-1] = not stack[-1]
            elif stack:
                stack.pop()
            continue
        if all(stack):
            out.append(line)
    return "".join(out)


MARIADB_REPO = "MariaDB/server"
MARIADB_FUNC_TABLES = [("sql/item_create.cc", "func_array"), ("sql/item_geofunc.cc", "func_array_geom")]


def generate_mysql(version: str, help_categories: list[tuple], help_topics: list[tuple],
                   privileges: list[tuple] = (), engine: str = "mysql") -> dict:
    maria = engine == "mariadb"
    repo = MARIADB_REPO if maria else MYSQL_REPO
    commit = resolve_commit(repo, f"{engine}-{version}")
    lex = parse_lex_h(fetch(repo, commit, MYSQL_KEYWORDS))
    keywords = {tok: text for tok, (text, _g) in lex.items()}
    word_group = {}
    for text, group in lex.values():  # a word listed both ways counts as a keyword
        word_group[text] = None if text in word_group and word_group[text] is None else group
    items, parsers = [], []
    for parser, gfile in ({"sql": "sql/sql_yacc.yy"} if maria else MYSQL_PARSERS).items():
        try:
            g = fetch(repo, commit, gfile)
        except Exception:  # noqa: BLE001 - sql_hints.yy exists since 5.7
            continue
        parsers.append(gfile)
        if maria:
            g = preprocess_bison_ifdef(g)
        items += [it for it in grammar_items(parser, g, None, keywords) if it["kind"] == "grammar"]
    kw_items = [{"id": f"kw:{w}", "kind": "keyword", **({"group": g} if g else {})} for w, g in sorted(word_group.items())]
    base = f"https://github.com/{repo}/blob/{commit}/"
    func_tables = MARIADB_FUNC_TABLES if maria else [(MYSQL_FUNC_TABLE, "func_array")]
    funcs = [f for file, table in func_tables
             for f in function_items(fetch(repo, commit, file), base, table=table, source_file=file)]
    docs = help_items(help_categories, help_topics)
    # static privileges are grammar keywords, dynamic ones (8.0+: BACKUP_ADMIN, ...) are only names
    privs = [{"id": f"priv:{row[0].upper().replace(' ', '_')}", "kind": "privilege"} for row in privileges]
    unique = {}
    for it in kw_items + sorted(items, key=lambda i: i["id"]) + funcs + privs + docs:
        unique.setdefault(it["id"], it)
    notes = [
        "Keywords: every name in sql/lex.h; group function = function-like word (COUNT, CAST, ...), group hint = word of the optimizer-hint parser only. information_schema.KEYWORDS (MySQL 8.0+) lists neither, so keyword lists leave them out.",
        "func: items are the native functions resolved by name (" + ", ".join(f"{t} in {f}" for f, t in func_tables) + "); functions with their own grammar (CAST, EXTRACT, aggregates, window functions, ...) are grammar items.",
        "priv: items are the privilege names of SHOW PRIVILEGES (static and, since MySQL 8.0, dynamic privileges, which the grammar reads as identifiers); grammar items ending in (name) are words the parser actions compare an identifier with (ALGORITHM = INSTANT, FORMAT = TREE).",
        "help: items are the topics of the server's HELP tables (mysql.help_topic), which are generated from the reference manual - names, categories and links only. Some categories are misfiled upstream (MySQL: JSON functions under Spatial Functions / MBR Functions, 9.x vector functions under Window Functions): classify by topic name.",
    ]
    if maria:
        notes += ["sql_yacc.yy is the default-mode branch of %ifdef MARIADB (sql_mode=ORACLE has its own generated grammar, 10.3 / 10.4 a separate sql_yacc_ora.yy) - Oracle mode is not inventoried.",
                  "Optimizer hints (12.x) are parsed by a hand-written parser (sql/opt_hints_parser.cc), not inventoried."]
    else:
        notes[3] += " The source tree has the HELP data only from 8.0 on (5.x: a placeholder file), and dev.mysql.com refuses automated requests."
    return {
        "engine": engine,
        "version": version,
        "generated_at": dt.date.today().isoformat(),
        "sources": [
            {"kind": "grammar", "repository": repo, "commit": commit,
             "files": parsers + [MYSQL_KEYWORDS] + [f for f, _t in func_tables]},
            {"kind": "server", "files": ["mysql.help_category", "mysql.help_topic", "SHOW PRIVILEGES"]},
        ],
        "notes": notes,
        "items": list(unique.values()),
    }


SPHINX_REPO = "sphinxsearch/sphinx"
SPHINX2_PARSERS = {
    "sphinxql": ("src/sphinxql.y", "src/sphinxql.l"),
    "sphinxexpr": ("src/sphinxexpr.y", None),
    "sphinxquery": ("src/sphinxquery.y", None),
    "sphinxselect": ("src/sphinxselect.y", None),
}


def docbook_items(xml: str, base_url: str) -> list[dict]:
    """Section titles of a DocBook manual (Sphinx 2.x doc/sphinx.xml)."""
    items = []
    for m in re.finditer(r'<sect(\d)\s+id="([^"]+)"[^>]*>\s*<title>(.*?)</title>', xml, re.S):
        title = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        items.append({"id": f"docs-page:{m.group(2)}: {' '.join(title.split())}", "kind": "docs",
                      "url": f"{base_url}#{m.group(2)}"})
    return items


def generate_sphinx(version: str, handshake: str, doc_markdown: str | None) -> dict:
    """2.x: grammar at the release commit (open source) + DocBook manual; 3.x: no sources are
    published, only the manual shipped in the binary archive (headings)."""
    items: list[dict] = []
    sources: list[dict] = []
    notes = []
    m = re.search(r"\(([0-9a-f]{7,})\)|commit ([0-9a-f]{7,})", handshake)
    short = (m.group(1) or m.group(2)) if m else None
    if version.startswith("2.") and short:
        commit = resolve_commit(SPHINX_REPO, short)
        keyword_parsers: dict[str, list[str]] = {}
        for parser, (gfile, lfile) in SPHINX2_PARSERS.items():
            g = fetch(SPHINX_REPO, commit, gfile)
            lx = fetch(SPHINX_REPO, commit, lfile) if lfile else None
            for it in grammar_items(parser, g, lx):
                if it["kind"] == "keyword":
                    keyword_parsers.setdefault(it["id"], []).append(parser)
                else:
                    items.append(it)
        items = [{"id": k, "kind": "keyword", "parsers": v} for k, v in sorted(keyword_parsers.items())] \
            + sorted(items, key=lambda i: i["id"])
        items += docbook_items(fetch(SPHINX_REPO, commit, "doc/sphinx.xml"), "https://sphinxsearch.com/docs/sphinx2.html")
        sources = [{"kind": "grammar", "repository": SPHINX_REPO, "commit": commit,
                    "files": [f for pair in SPHINX2_PARSERS.values() for f in pair if f]},
                   {"kind": "docs-index", "repository": SPHINX_REPO, "commit": commit, "files": ["doc/sphinx.xml"]}]
    elif doc_markdown is not None:
        items = page_items(doc_markdown, "sphinx3", "https://sphinxsearch.com/docs/")
        sources = [{"kind": "docs-index", "files": ["doc/sphinx3.md (vendor binary archive)"]}]
        notes.append("Sphinx 3 publishes no parser sources: only the manual's headings are inventoried, so keywords and grammar forms are missing - check them against the server.")
    unique = {}
    for it in items:
        unique.setdefault(it["id"], it)
    return {"engine": "sphinx", "version": version, "generated_at": dt.date.today().isoformat(),
            "sources": sources, "notes": notes, "items": list(unique.values())}


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
