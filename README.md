# pkgsite

The builder for [pkg.xolang.org](https://pkg.xolang.org): documentation pages for
[Xo](https://xolang.dev)'s standard library and for modules published through
proxy.xolang.org.

Status: the `build` and `publish` jobs are in place; `publish` uploads
nothing until the owner sets the R2 secrets (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`). The design
is decision 0589 in
[xo-lang/xo](https://github.com/xo-lang/xo/blob/main/knowledgebase/decisions/0589-pkg-docs-site.md).

## How it works

- `.github/workflows/build.yml` runs every 30 minutes and on demand. It reads
  index.xolang.org's feed for new versions, fetches each with the released
  xo through proxy.xolang.org (xo checks it against sum.xolang.org, the
  repository variable `XO_SUMDB`), and renders its docs with `xo doc --json`
  in a network namespace (an unprivileged one, else `sudo unshare --net`
  with xo dropped back to the runner's user; the build fails when neither
  works), so a module's source is parsed with no network and never run.
- A version with no recognized license file gets a page saying so and no
  docs, as on pkg.go.dev.
- The `build` job has no secrets and a read only token; it uploads the site
  and the new feed position (`state/position.json`) as artifacts.
- The `publish` job (main only) downloads the site artifact and writes it to
  the `xo-pkgsite` R2 bucket with `scripts/publish-r2.sh`, using a token
  scoped to that bucket only: secrets `R2_ACCESS_KEY_ID` and
  `R2_SECRET_ACCESS_KEY` and `R2_ENDPOINT` (a secret, so the run log masks the account id)
  (`https://<account id>.r2.cloudflarestorage.com`). It never sees module
  source. It adds and replaces files and never deletes; `catalog.json` goes
  last, so the next build never takes a page as built before it is uploaded.
  With the secrets unset it prints a notice and publishes nothing.
  `DRY_RUN=1 scripts/publish-r2.sh SITE` lists each upload with its content
  type and cache header.
- The `heartbeat` job (scheduled runs) commits `state/heartbeat` once a day
  so GitHub keeps the schedule running, and commits `state/position.json`
  when a publish uploaded the pages built up to it; a failed or skipped
  publish leaves the position, so the next run builds those versions again.
- Removing a module from the proxy (see the proxy's policy) removes its pages.

## Std at each release (stage a)

    scripts/render-std.sh v0.46.0 OUT

installs that release's xo (checked against its SHA256SUMS), renders its
std into `OUT/site` merged with the published catalog, and lists every file
with its content type in `OUT/upload.txt` for the release's upload step. It
uploads nothing.

Before uploading, check the staged site (`OUT/site` served on loopback):

    (cd OUT/site && python3 -m http.server 8000 --bind 127.0.0.1) &
    python3 -I scripts/sitecheck/crawl.py http://127.0.0.1:8000 OUT/site
    (cd OUT/site && find . -name '*.html' | sed 's|^\.||') > /tmp/pages.txt
    node scripts/sitecheck/width.mjs http://127.0.0.1:8000 /tmp/pages.txt "$(mktemp -d)"

crawl.py fetches every page and every local link, checks each `#anchor`
exists and no page repeats an id; width.mjs reports any page wider than a
390 px phone.

## Layout of the site

    /<module>@<version>/index.html          the module's root package
    /<module>@<version>/<package>/index.html
    /<module>/index.html                    a redirect to the latest version
    /<module>/versions.html
    /std/<name>@<xo version>/index.html
    /catalog.json, /search/index.json

Symbols are anchored by their exact name (`#Client.get`).

## Running it locally

    python3 -E -s -m unittest discover -s tests -t .
    python3 -E -s -m builder.build --xo "$(command -v xo)" --work /tmp/pk-work \
      --site /tmp/pk-site --proxy direct --no-verify \
      --module github.com/xo-lang/aws@v0.1.0 --std

`--no-verify` skips the checksum log and is for local runs only; the
workflow always verifies.

Run `scripts/check-public.sh` before every push.

## License

MIT, see [LICENSE](LICENSE).
