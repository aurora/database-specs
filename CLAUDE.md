# database-specs

Machine-readable, versioned specifications of SQL engines (MySQL, MariaDB, PostgreSQL, SQL Server, SQLite, Manticore, Sphinx so far)
for database clients: lexical rules, wire-protocol type codes, capabilities, introspection
queries, client operations and curated statement syntax. Implementation-agnostic: nothing in
here may depend on a particular client, language or driver. Content is written in English.

## Look things up with `dbspecs show`, not by reading YAML

Version resolution has rules that are easy to get wrong by hand (`since` inclusive, `until`
exclusive, last matching entry wins, missing = `unknown`). `dbspecs show` applies them:

```bash
uv run dbspecs show profile -e mariadb -v 11.4                 # everything for one server version
uv run dbspecs show capability returning -e mysql -v 8.0.13
uv run dbspecs show query list-indexes -e postgresql -v 16       # contract + exact SQL variant
uv run dbspecs show operation change-column-type -e mysql -v 8.4
uv run dbspecs show syntax create-index -e mysql -v 5.7 --sql "CREATE INDEX i ON t ((a+1))"
uv run dbspecs show keywords rank -e mysql -v 8.0.30              # is a word reserved? (or the full lists)
uv run dbspecs show list                                          # all ids
```

Add `--json` for machine-readable output. Exit code 3 = the query has no variant for that
version (a documented gap, see `gaps`).

## Commands

```bash
uv run dbspecs validate     # schemas, cross references, offline grammar/example checks - run after every change
uv run dbspecs test         # real servers in containers (docker/podman); ~15 min for all targets
uv run dbspecs test --target mariadb-10.6 --target postgresql   # subset: target id or engine
uv run dbspecs test --target manticore --extended  # include tier: extended targets (older versions)
uv run dbspecs build        # dist/db-specs.json + dist/syntax/ (railroad diagrams)
uv run dbspecs keywords     # regenerate keywords/<engine>/<version>.yaml from the test targets
uv run dbspecs coverage     # COVERAGE.md + dist/coverage.html (also written after every test run)
uv run dbspecs inventory --target manticore --extended   # inventory/<engine>/<version>.yaml from each server's sources (manticore, sphinx, mysql, mariadb, postgresql)
uv run dbspecs inventory-diff manticore 27.1.5 28.4.4    # grammar items added (+) / removed (-) between versions
```

## Layout

- `engines/`, `protocols/`, `lexical/`: one YAML per engine / wire protocol / dialect. An engine lists
  its protocols as profiles (`protocols: [{ id: mysql, default_port: 9306, handshake, type_mapping,
  type_probe }]`): the wire format stays shared, engine differences live in the profile, and
  `type_probe` verifies the type codes / flags on every test target.
- `capabilities/<area>/<name>.yaml`: id = `<area>.<name>`, versioned support + executable probes.
- `operations/<area>/<name>.yaml`: SQL templates for things a client generates.
- `queries/<area>/<name>/`: `query.yaml` (contract) + one `.sql` per engine/version variant.
- `syntax/<area>/<name>/`: `syntax.yaml` (examples) + `<engine>.ebnf`.
- `COVERAGE.md` (generated, checked in): matrix spec x engine - tested / partial / documented /
  not applicable / missing. `roadmap.yaml`: planned specs that do not exist yet.
- Engines without catalog views (Manticore: SHOW / DESCRIBE only) map engine-native result
  columns to the query contract with a variant `transform` (+ `inline_parameters` for names that
  cannot be placeholders, `extra_columns` for engine-specific data). Languages embedded in string
  literals (the MATCH() query of Manticore / Sphinx) are syntax specs with `wrap` and their own
  tokenizer lexical (`lexical: fulltext-query`), referenced from the engine lexical spec's
  `embedded_languages`.
- `inventory/<engine>/<version>.yaml` (generated): everything the engine has - keywords and grammar
  forms from its parser sources at the build commit, plus the built-in function table (`func:`) and the manual's reference index
  (MySQL / MariaDB: sql_yacc.yy (MariaDB: its default-mode %ifdef branch) / sql_hints.yy / lex.h / item_create.cc at the release tag, topics of the server's HELP tables as
  `help:` items; PostgreSQL: gram.y / kwlist.h, the PL/pgSQL grammar, the SQL command reference pages and the server's
  pg_catalog functions / types; keywords with a `group` (function, hint, plpgsql) are not SQL keywords and stay out of the keyword lists).
  `scope/<engine>.yaml` classifies every item (covered by specs / planned in the roadmap / open /
  out-of-scope with a reason); `validate` fails on unclassified items. `/audit-inventory <engine>`
  runs an independent review in a fresh subagent and writes `dist/audit/`.
- `keywords/<engine>/<version>.yaml`: generated keyword lists (never edit by hand; `test` fails
  when a stored list no longer matches its server version).
- `tests/targets.yaml` (container images; `build: tests/images/<dir>` for engines without an
  official image - the Dockerfile uses the vendor's release files and pins their checksum, and a
  fixture config can predefine tables, as for Sphinx 2.x which has no CREATE TABLE),
  `tests/cases/` (integration tests). Embedded engines
  (SQLite) run `tooling/dbspecs/sqlite_worker.py` inside a `python:*-slim` image (that Debian's
  libsqlite3) or locally; setup entries can be `{sql, since, until}` for version-specific DDL.
- `schemas/` JSON Schemas; `tooling/dbspecs/` Python tooling.

## Rules for changing specs

- **Observe before asserting.** Before writing expectations for a new query or fixture, run it
  against the real servers and look at the raw output; engines differ in surprising ways
  (quoted vs unquoted defaults, 'NULL' strings, default FK actions, ignored DESC).
- **Never weaken a test to make it pass.** A failing probe or test means the spec is wrong or
  the version range is - fix the spec, or narrow the range and document why.
- **`unknown` is not `unsupported`.** Only write `unsupported` when it is checked (probe/test)
  or documented. Mark unchecked facts with `sources: [{ evidence: unverified }]`.
- **Every query variant must return exactly the contract's columns**, in order, with the
  declared types/nullability/enums (the test runner enforces this). Add result notes to the
  variant when an engine reports something differently.
- **New version range?** Add a test target to `tests/targets.yaml` if an image exists, so the
  range boundary is exercised.
- **Older versions** (`tier: extended` targets, run with `--extended`): test a sample - every
  supported release line, the oldest version still in real use, and every known boundary - then
  narrow failures by bisecting with intermediate images. For engines with an inventory, the
  grammar diff (`inventory-diff`) gives syntax boundaries directly; bisect only for behaviour
  (wire flags, no-ops, semantics). Record what was tested: `since` = first version observed with
  the feature, a counter-example `until` the next series after the last version observed without
  it; never claim anything for versions without an image (say so in a note). Keep boundary
  versions as permanent extended targets. A test whose query has no variant for a version is
  skipped as a documented gap; to widen a range, run the oldest variant against the older server
  (all tests that exercise it must pass) and record failed attempts in `gaps`.
- **Syntax examples** declare `expect: valid | invalid | semantic-error` per engine/version
  range; `validate` checks them offline for every version series, `test` against servers.
  Version annotations in EBNF (`/* @since X */`) apply to the single next item.
- **Operations are tested by their effect**: run the operation in a test case, then verify with
  introspection queries or an ad-hoc `sql` step. Operations that return DDL (`result_column`)
  need a `roundtrip` step (snapshot, drop, re-run the DDL, compare) - that is what proves the
  reconstruction is complete.
- **Completeness comes from the inventory, not from memory.** Before writing specs for an engine
  area, look at its inventory items; after writing them, move the matching scope rules to
  `covered`. A new engine version means: regenerate the inventory, then classify the new items.
- **Planning**: new work starts from `roadmap.yaml`; once a spec file exists, remove its roadmap
  item (`validate` complains otherwise) and regenerate COVERAGE.md. Where an engine lacks a feature
  entirely, say so explicitly (`status: unsupported`, or `not_applicable` in query contracts) so
  the matrix shows ➖ instead of a gap.
- Test results are kept per target (`dist/verification/<target>.json`); a run with `--target`
  only replaces those targets, the matrix uses the latest result of every target.
- **Derived engines** get their own files; `extends` is lineage only, nothing is inherited.
- **No vendor documentation prose** (MySQL docs are not freely licensed): facts in our own
  words, link the source.
- Keep JSON schemas hand-formatted (no re-dumping with json.dumps).
