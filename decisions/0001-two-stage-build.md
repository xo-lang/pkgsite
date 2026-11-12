# 0001: two stage build, render only rebuilds

Status: Proposed (owner approved the direction 2026-11-12; this record
amends xo-lang/xo decision 0589 for this repository)

## Context

Every page was made in one pass: fetch the version through the proxy, check
it against sum.xolang.org, run `xo doc --json` with no network, render HTML.
A change to the page template or style could only reach the 2164 published
versions by fetching and documenting each again, 400 a run (about an hour
each), so about six runs, and the catalog had no record of which renderer
made a page, so a rebuild could not target only stale pages.

## Decision

1. Two stages in `builder/build.py`:
   - (a) `gather`: fetch, license, `xo doc --json`. Its result, the doc
     record, is stored next to the pages at
     `/_doc/<module>/@v/<version>.json` (schema `DOC_SCHEMA`, the module
     path and version, the xo version that made it, the license files and
     each package's doc JSON). No HTML.
   - (b) `render_version`: HTML from a doc record only. It runs no xo and
     reads no module source.
   A feed build runs both and publishes the record with the pages.
2. The catalog records, per version, `xo` (the xo that made the docs) and
   `renderer` (`RENDERER`, a constant bumped on any change to how a record
   becomes HTML; builds without it are renderer 0).
3. A rebuild (`--rebuild SELECTOR`, the workflow's `rebuild` input) takes
   versions the catalog already has: `all`, an SDK (`aws`, `azure`, `gcp`,
   `openai`: its repository's modules) or a module path pattern. `--stage
   render` runs (b) from the published records; `--stage full` runs both.
   `--stale` keeps only builds an older renderer made (full: or an older
   xo). The workflow shards it across a matrix (`shards`, 1 to 16, default
   8); each shard writes pages and a catalog part, and `rebuild-finish`
   folds the parts into the published catalog and writes the catalog wide
   pages. A rebuild never reads or writes `state/position.json`, and the
   workflow's single concurrency group keeps it from overlapping a feed run.

## Consequences

- A template or style change: bump `RENDERER`, merge, dispatch `rebuild:
  all, stage: render`. Minutes, no xo, no proxy traffic.
- Versions built before this change have no stored record: a render rebuild
  reports them as failed (with a warning per version), and one `stage:
  full` rebuild (stale) gives every version its record. That first full
  rebuild is a public deploy, the owner's call.
- A new xo that changes `xo doc --json`: `rebuild: all, stage: full` with
  `stale` rebuilds only versions an older xo documented.
- The doc records are public, as the pages they render are.

## Alternatives

- Keep one pass and raise the batch size: still fetches and runs xo doc for
  every version on every template change.
- Store the records in the repository: thousands of files in git, and the
  build job would need write access.
