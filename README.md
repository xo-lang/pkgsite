# pkgsite

The builder for [pkg.xolang.org](https://pkg.xolang.org): documentation pages for
[Xo](https://xolang.dev)'s standard library and for modules published through
proxy.xolang.org.

Status: not built yet. The design is decision 0589 in
[xo-lang/xo](https://github.com/xo-lang/xo/blob/main/knowledgebase/decisions/0589-pkg-docs-site.md).

How it will work:

- A scheduled GitHub Actions workflow reads index.xolang.org for new module
  versions, fetches each through proxy.xolang.org, verifies it against
  sum.xolang.org, and renders its docs with `xo doc --json`.
- The `build` job has no secrets; module source is only parsed, never run.
  A separate `publish` job uploads the pages to the site's storage.
- Removing a module from the proxy (see the proxy's policy) removes its pages.

## License

MIT, see [LICENSE](LICENSE).
