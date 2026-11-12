"""The feed position file the heartbeat job commits: only a since
timestamp, a heartbeat timestamp and the failure counts run_todo keeps
for versions it will retry (module path@version to a run count)."""

import json
import re
import sys

STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~/-]*@v[0-9A-Za-z.+-]+")


def valid(d):
    """True when d holds only the position's own fields, well formed."""
    if not isinstance(d, dict) or not set(d) <= {"since", "heartbeat", "failures"}:
        return False
    for k in ("since", "heartbeat"):
        if k in d and not (isinstance(d[k], str) and STAMP.fullmatch(d[k])):
            return False
    f = d.get("failures", {})
    return isinstance(f, dict) and all(
        isinstance(k, str) and KEY.fullmatch(k) and type(n) is int and 1 <= n <= 100 for k, n in f.items())


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        sys.exit(0 if valid(json.load(fh)) else 1)
