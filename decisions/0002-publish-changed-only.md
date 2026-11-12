# 0002: publish sends only the pages that changed

Status: accepted by the owner, 2026-11-12.

## Context

A full rebuild (run 43267540480) made 7897 files, 1.0 GB, and its
publish, one put per file 16 at a time, did not finish in 30 minutes.
Most of those bytes were already in the bucket: the `_doc` JSON of a
version does not change when only the renderer does, and a retried
publish sends again what the failed one already sent.

## Decision

`scripts/publish-r2.sh` lists the bucket once (`list-objects-v2`, key
and ETag) and `scripts/changed.py` drops every page whose MD5 equals its
object's ETag. `put-object` stores an object in one part, and R2, like
S3, gives such an object its MD5 in hex as the ETag, so equal means the
bucket already has those bytes. A multipart ETag (with a `-`) never
matches, so such a file is sent again. `search/index.json`, `index.html`
and `catalog.json` are always sent, last, as before.

`PUBLISH_ALL=1` sends every page (a bucket whose ETags are not to be
trusted). A listing that is not JSON stops the publish before any put.

## Consequences

- A retried publish, and a rebuild whose `_doc` JSON is unchanged, sends
  only what differs; the log line says how many pages were unchanged.
- Each rendered page carries the build day ("Generated ... on DAY"), so
  a rebuild on a later day still sends every HTML page; only same-day
  retries and unchanged JSON are skipped. Taking the day from the
  version's record instead would make render-only rebuilds byte-stable.
- One listing call per publish (about 8 pages of 1000 keys).

## Alternatives

- A manifest of hashes stored in the bucket: one more file to keep in
  step with the objects, and wrong after any upload outside this script.
  The ETags are the bucket's own record.
- `aws s3 sync`: compares size and time, not content, and a rebuilt
  page has a new time.
