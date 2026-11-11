#!/bin/sh
# publish-r2.sh SITE: uploads a built site (the build job's artifact) to the
# R2 bucket that serves pkg.xolang.org (decision 0589), through R2's S3 API
# with the aws CLI. It only adds and replaces files: it never deletes, so a
# takedown stays a deliberate, separate step.
#
# Environment:
#   R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY  a token scoped to the bucket only
#   R2_ENDPOINT   https://<account id>.r2.cloudflarestorage.com (a repository
#                 variable, so the account id is not in this repository)
#   R2_BUCKET     default xo-pkgsite
#   DRY_RUN=1     print each upload instead of running it (no credentials needed)
#
# Order: every page first, then search/index.json, index.html and last
# catalog.json. The next build reads the published catalog.json to know
# what is already built, so it must never name a page that is not there yet.
set -eu
site=${1:?usage: publish-r2.sh SITE}
[ -f "$site/catalog.json" ] || { echo "publish-r2: $site/catalog.json is missing; not a built site" >&2; exit 2; }
bucket=${R2_BUCKET:-xo-pkgsite}
if [ "${DRY_RUN:-0}" != 1 ]; then
  : "${R2_ACCESS_KEY_ID:?publish-r2: R2_ACCESS_KEY_ID is not set}"
  : "${R2_SECRET_ACCESS_KEY:?publish-r2: R2_SECRET_ACCESS_KEY is not set}"
  : "${R2_ENDPOINT:?publish-r2: R2_ENDPOINT is not set}"
  case $R2_ENDPOINT in
    https://*.r2.cloudflarestorage.com) ;;
    *) echo "publish-r2: R2_ENDPOINT must be https://<account id>.r2.cloudflarestorage.com" >&2; exit 2 ;;
  esac
  export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  export AWS_DEFAULT_REGION=auto AWS_EC2_METADATA_DISABLED=true
  # R2 rejects the CLI's default request checksums (aws CLI 2.23 and later)
  export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
  unset AWS_PROFILE AWS_SESSION_TOKEN
fi

ctype() {
  case $1 in
    *.html) echo "text/html; charset=utf-8" ;;
    *.json) echo "application/json" ;;
    *.css) echo "text/css; charset=utf-8" ;;
    *.js) echo "text/javascript; charset=utf-8" ;;
    *.svg) echo "image/svg+xml" ;;
    *.txt) echo "text/plain; charset=utf-8" ;;
    *) echo "application/octet-stream" ;;
  esac
}

# a version's pages never change once built; the lists, redirects and the
# catalog do, so they are cached briefly
cache() {
  case $1 in
    *@*/*) echo "public, max-age=86400" ;;
    *) echo "public, max-age=300" ;;
  esac
}

n=0
put() {
  f=$1
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf 'put %s\t%s\t%s\n' "$f" "$(ctype "$f")" "$(cache "$f")"
  else
    aws s3api put-object --endpoint-url "$R2_ENDPOINT" --bucket "$bucket" --key "$f" \
      --body "$site/$f" --content-type "$(ctype "$f")" --cache-control "$(cache "$f")" > /dev/null
  fi
  n=$((n + 1))
}

last="search/index.json index.html catalog.json"
list=$(cd "$site" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)
# one name per line (a here-document keeps the loop in this shell, so its
# exit and the count apply); any name outside the site's characters stops
# the upload before anything is sent
while IFS= read -r f; do
  case $f in
    *[!A-Za-z0-9._@/+~!-]*) echo "publish-r2: refusing an unexpected file name: $f" >&2; exit 2 ;;
  esac
done <<EOF
$list
EOF
while IFS= read -r f; do
  case " $last " in *" $f "*) continue ;; esac
  put "$f"
done <<EOF
$list
EOF
for f in $last; do
  [ -f "$site/$f" ] && put "$f"
done
echo "publish-r2: $n file(s) to $bucket"
