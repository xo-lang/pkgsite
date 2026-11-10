#!/bin/sh
# render-std.sh VERSION OUT: stage (a) of decision 0589, run at each Xo
# release. Installs the released xo VERSION (checked against the release's
# SHA256SUMS), renders its std into OUT/site merged with the published
# catalog, and writes OUT/upload.txt: each file's path and content type, for
# the release's upload step (this script uploads nothing).
#   OUT/site/std/<name>@<version>/index.html, std/<name>/index.html,
#   index.html, catalog.json, search/index.json
# CATALOG (default https://pkg.xolang.org/catalog.json) names another
# catalog, a file or "" for none.
set -eu
v=${1:?usage: render-std.sh VERSION OUT}
out=${2:?usage: render-std.sh VERSION OUT}
here=$(cd "$(dirname "$0")/.." && pwd)
[ ! -e "$out/site" ] || { echo "render-std: $out/site exists; give an empty OUT" >&2; exit 2; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
"$here/scripts/install-xo.sh" "$v" "$out/xo" >/dev/null
got=$("$out/xo/bin/xo" version | awk '{print "v" $2}')
[ "$got" = "$v" ] || { echo "render-std: the release's xo says $got, not $v" >&2; exit 1; }
(cd "$here" && python3 -E -s -m builder.build --xo "$out/xo/bin/xo" --work "$out/work" \
  --site "$out/site" --feed none --std --catalog "${CATALOG-https://pkg.xolang.org/catalog.json}")
n=$(find "$out/site/std" -path "*@$v/index.html" | wc -l | tr -d ' ')
[ "$n" -gt 0 ] || { echo "render-std: no std page rendered" >&2; exit 1; }
(cd "$out/site" && find . -type f | sed 's|^\./||' | sort | while read -r f; do
  case $f in
    *.html) t="text/html; charset=utf-8" ;;
    *.json) t="application/json" ;;
    *) t="application/octet-stream" ;;
  esac
  printf '%s\t%s\n' "$f" "$t"
done) > "$out/upload.txt"
echo "render-std: $n std modules for $v in $out/site; $(wc -l < "$out/upload.txt" | tr -d ' ') files in $out/upload.txt"
