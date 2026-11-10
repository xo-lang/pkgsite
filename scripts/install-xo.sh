#!/bin/sh
# install-xo.sh VERSION DIR: the released xo for this machine (linux or
# darwin, amd64 or arm64) into DIR (DIR/bin/xo), checked against the
# release's SHA256SUMS.
set -eu
v=${1:?usage: install-xo.sh VERSION DIR}
dir=${2:?usage: install-xo.sh VERSION DIR}
case $v in v[0-9]*.[0-9]*.[0-9]*) ;; *) echo "install-xo: bad version $v" >&2; exit 2 ;; esac
case $(uname -s) in Linux) os=linux ;; Darwin) os=darwin ;; *) echo "install-xo: unsupported OS" >&2; exit 2 ;; esac
case $(uname -m) in x86_64|amd64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; *) echo "install-xo: unsupported CPU" >&2; exit 2 ;; esac
tar=xo-$v-$os-$arch.tar.gz
base=https://github.com/xo-lang/xo/releases/download/$v
tmp=$(mktemp -d)
trap 'rm -rf "${tmp:?}"' EXIT
curl -fsSL --retry 3 -o "$tmp/$tar" "$base/$tar"
curl -fsSL --retry 3 -o "$tmp/SHA256SUMS" "$base/SHA256SUMS"
want=$(awk -v f="$tar" '$2 == f || $2 == "*" f {print $1}' "$tmp/SHA256SUMS")
if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$tmp/$tar" | awk '{print $1}'); else got=$(shasum -a 256 "$tmp/$tar" | awk '{print $1}'); fi
[ -n "$want" ] && [ "$want" = "$got" ] || { echo "install-xo: $tar does not match SHA256SUMS" >&2; exit 1; }
mkdir -p "$dir"
tar -xzf "$tmp/$tar" -C "$dir" --strip-components=1
"$dir/bin/xo" version
