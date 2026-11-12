"""changed.py SITE LISTING: reads file names (one per line) on stdin and
prints those whose bytes differ from the bucket's copy. LISTING is the
JSON of `aws s3api list-objects-v2 --query "Contents[].[Key,ETag]"` (a
list of [key, etag] pairs, or null for an empty bucket). An object put in
one part (put-object) has its MD5 in hex as its ETag, so a file whose MD5
matches is already there byte for byte. A multipart ETag (it has a "-")
never matches, so such a file is sent again."""

import hashlib
import json
import sys


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def etags(listing):
    """key -> ETag without its quotes."""
    out = {}
    for row in listing or []:
        if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str) and isinstance(row[1], str):
            out[row[0]] = row[1].strip('"').lower()
    return out


def changed(site, names, have):
    for n in names:
        if have.get(n) != md5(site + "/" + n):
            yield n


def main(argv):
    site, listing = argv[1], argv[2]
    with open(listing, encoding="utf-8") as f:
        have = etags(json.load(f))
    names = [l.rstrip("\n") for l in sys.stdin if l.strip()]
    for n in changed(site, names, have):
        print(n)


if __name__ == "__main__":
    main(sys.argv)
