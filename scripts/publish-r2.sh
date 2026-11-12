#!/bin/sh
# publish-r2.sh SITE: uploads a built site (the build job's artifact) to the
# R2 bucket that serves pkg.xolang.org (decision 0589), through R2's S3 API
# with the aws CLI. It only adds and replaces files: it never deletes, so a
# takedown stays a deliberate, separate step.
#
# Environment:
#   R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY  a token scoped to the bucket only
#   R2_ENDPOINT   https://<account id>.r2.cloudflarestorage.com (a repository
#                 secret, so the account id is neither in this repository
#                 nor in the public run log)
#   R2_BUCKET     default xo-pkgsite
#   DRY_RUN=1     print each upload instead of running it (no credentials needed)
#   PUBLISH_ALL=1 send every page, not only those that differ from the bucket
#   PUBLISH_LISTING  a list-objects-v2 [key, etag] listing to compare against
#                 instead of asking the bucket
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

# every file is cached briefly: a version's pages are rebuilt whenever the
# renderer changes (the std pages on every --std run), and a day-long cache
# kept the old pages live for a day after the 2026-11-11 restyle
cache() {
  echo "public, max-age=300"
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
pages=$(printf '%s\n' "$list" | while IFS= read -r f; do
  case " $last " in (*" $f "*) continue ;; esac
  printf '%s\n' "$f"
done)
# only the pages whose bytes differ from the bucket's (decision 0002):
# one listing of the bucket, then each page's MD5 against its object's
# ETag. PUBLISH_ALL=1 sends every page; PUBLISH_LISTING names a listing
# file to use instead of asking the bucket (the tests, a dry run).
total=$(printf '%s\n' "$pages" | grep -c . || true)
if [ "${PUBLISH_ALL:-0}" != 1 ] && [ -n "$pages" ]; then
  listing=${PUBLISH_LISTING:-}
  if [ -z "$listing" ] && [ "${DRY_RUN:-0}" != 1 ]; then
    listing=$(mktemp)
    aws s3api list-objects-v2 --endpoint-url "$R2_ENDPOINT" --bucket "$bucket" \
      --query 'Contents[].[Key,ETag]' --output json > "$listing"
  fi
  if [ -n "$listing" ]; then
    pages=$(printf '%s\n' "$pages" | python3 -I "$(dirname "$0")/changed.py" "$site" "$listing")
  fi
fi
skipped=$((total - $(printf '%s\n' "$pages" | grep -c . || true)))
if [ "${DRY_RUN:-0}" = 1 ] || [ "${PUBLISH_JOBS:-16}" -le 1 ]; then
  while IFS= read -r f; do
    [ -n "$f" ] && put "$f"
  done <<EOF
$pages
EOF
elif [ -n "$pages" ]; then
  # the pages PUBLISH_JOBS (default 16) at a time: one put a file took
  # 12 minutes for 400 versions (2026-11-12), a full rebuild's 2164 past
  # the publish job's limit. The names were checked above; every page is
  # up before the last files go (xargs waits for all and fails if any did).
  printf '%s\n' "$pages" | PUBLISH_SITE=$site PUBLISH_BUCKET=$bucket \
    xargs -P "${PUBLISH_JOBS:-16}" -n 1 sh -c '
      f=$1
      case $f in
        *.html) t="text/html; charset=utf-8" ;; *.json) t="application/json" ;;
        *.css) t="text/css; charset=utf-8" ;; *.js) t="text/javascript; charset=utf-8" ;;
        *.svg) t="image/svg+xml" ;; *.txt) t="text/plain; charset=utf-8" ;; *) t="application/octet-stream" ;;
      esac
      aws s3api put-object --endpoint-url "$R2_ENDPOINT" --bucket "$PUBLISH_BUCKET" --key "$f" \
        --body "$PUBLISH_SITE/$f" --content-type "$t" --cache-control "public, max-age=300" > /dev/null || exit 255' _
  n=$(printf '%s\n' "$pages" | wc -l | tr -d ' ')
fi
for f in $last; do
  [ -f "$site/$f" ] && put "$f"
done
echo "publish-r2: $n file(s) to $bucket, $skipped page(s) unchanged"
