# database-specs

Machine-readable, versioned specifications of SQL engines (MySQL, MariaDB, PostgreSQL, SQL Server, SQLite so far)
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
uv run dbspecs build        # dist/db-specs.json + dist/syntax/ (railroad diagrams)
uv run dbspecs keywords     # regenerate keywords/<engine>/<version>.yaml from the test targets
uv run dbspecs coverage     # COVERAGE.md + dist/coverage.html (also written after every test run)
```

## Layout

- `engines/`, `protocols/`, `lexical/`: one YAML per engine / wire protocol / dialect.
- `capabilities/<area>/<name>.yaml`: id = `<area>.<name>`, versioned support + executable probes.
- `operations/<area>/<name>.yaml`: SQL templates for things a client generates.
- `queries/<area>/<name>/`: `query.yaml` (contract) + one `.sql` per engine/version variant.
- `syntax/<area>/<name>/`: `syntax.yaml` (examples) + `<engine>.ebnf`.
- `COVERAGE.md` (generated, checked in): matrix spec x engine - tested / partial / documented /
  not applicable / missing. `roadmap.yaml`: planned specs that do not exist yet.
- `keywords/<engine>/<version>.yaml`: generated keyword lists (never edit by hand; `test` fails
  when a stored list no longer matches its server version).
- `tests/targets.yaml` (container images), `tests/cases/` (integration tests). Embedded engines
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
- **Syntax examples** declare `expect: valid | invalid | semantic-error` per engine/version
  range; `validate` checks them offline for every version series, `test` against servers.
  Version annotations in EBNF (`/* @since X */`) apply to the single next item.
- **Operations are tested by their effect**: run the operation in a test case, then verify with
  introspection queries or an ad-hoc `sql` step. Operations that return DDL (`result_column`)
  need a `roundtrip` step (snapshot, drop, re-run the DDL, compare) - that is what proves the
  reconstruction is complete.
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
