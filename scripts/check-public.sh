#!/bin/sh
# check-public.sh: fails when tracked files hold data that must not be
# public: home directory paths, email addresses (but documentation domains
# and the Actions bot's), IP addresses outside loopback and the
# documentation ranges, private keys and tokens. Then runs gitleaks over
# the whole history and the working tree (GITLEAKS_CONFIG names a config).
# Run it before every push.
set -u
cd "$(dirname "$0")/.."
fail=0
files=$(git ls-files | grep -v -E '^(LICENSE|scripts/check-public\.sh)$')

report() {
  echo "check-public: $1" >&2
  echo "$2" | head -20 >&2
  fail=1
}

scan() {
  # $1 label, $2 pattern, $3 allow pattern (removed from each line first)
  out=$(echo "$files" | xargs grep -n -I -E -e "$2" | sed -E "s#$3##g" | grep -E -e "$2")
  [ -z "$out" ] || report "$1" "$out"
}

scan "home directory paths" '/(Users|home)/[A-Za-z0-9._-]+' '/home/runner'
scan "email addresses" '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' '41898282\+github-actions\[bot\]@users\.noreply\.github\.com|[A-Za-z0-9._%+-]+@example\.(com|org|net)|modules@xolang\.org'
scan "IP addresses" '(^|[^0-9.])([0-9]{1,3}\.){3}[0-9]{1,3}([^0-9.]|$)' '127\.0\.0\.1|0\.0\.0\.0|192\.0\.2\.[0-9]+|198\.51\.100\.[0-9]+|203\.0\.113\.[0-9]+'
scan "private keys" '-----BEGIN [A-Z ]*PRIVATE KEY-----' '^$'
scan "tokens" '(gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})' '^$'

if command -v gitleaks >/dev/null 2>&1; then
  cfg=""
  [ -n "${GITLEAKS_CONFIG:-}" ] && cfg="--config=$GITLEAKS_CONFIG"
  gitleaks git $cfg --no-banner --redact . >/dev/null 2>&1 || { echo "check-public: gitleaks found secrets in the history (gitleaks git --redact . -v)" >&2; fail=1; }
  gitleaks dir $cfg --no-banner --redact . >/dev/null 2>&1 || { echo "check-public: gitleaks found secrets in the working tree (gitleaks dir --redact . -v)" >&2; fail=1; }
else
  echo "check-public: gitleaks is not installed" >&2
  fail=1
fi
[ $fail -eq 0 ] && echo "check-public: ok"
exit $fail
