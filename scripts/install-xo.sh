#!/bin/sh
# install-xo.sh VERSION DIR: the released xo for linux/amd64 into DIR
# (DIR/bin/xo), checked against the release's SHA256SUMS.
set -eu
v=${1:?usage: install-xo.sh VERSION DIR}
dir=${2:?usage: install-xo.sh VERSION DIR}
case $v in v[0-9]*.[0-9]*.[0-9]*) ;; *) echo "install-xo: bad version $v" >&2; exit 2 ;; esac
tar=xo-$v-linux-amd64.tar.gz
base=https://github.com/xo-lang/xo/releases/download/$v
tmp=$(mktemp -d)
curl -fsSL --retry 3 -o "$tmp/$tar" "$base/$tar"
curl -fsSL --retry 3 -o "$tmp/SHA256SUMS" "$base/SHA256SUMS"
(cd "$tmp" && grep " $tar\$" SHA256SUMS | sha256sum -c -)
mkdir -p "$dir"
tar -xzf "$tmp/$tar" -C "$dir" --strip-components=1
rm -rf "${tmp:?}"
"$dir/bin/xo" version
