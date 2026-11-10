"""License detection for a module version (decision 0589: no license, no docs).

A module's license is read from the files at its root whose name starts with
LICENSE, LICENCE or COPYING (any case, any extension), as pkg.go.dev does. Each
is classified by the text a license always carries; a file that matches none
is "unknown", and a module whose files are all unknown (or that has none) gets
no rendered docs, only a page saying why.
"""

import os
import re

# (SPDX id, the phrases that identify it; every phrase must appear). Checked in
# order, so the more specific BSD-3-Clause comes before BSD-2-Clause.
KNOWN = [
    ("Apache-2.0", ["apache license", "version 2.0", "terms and conditions for use, reproduction, and distribution"]),
    ("MIT", ["permission is hereby granted, free of charge, to any person obtaining a copy", "the above copyright notice and this permission notice shall be included"]),
    ("BSD-3-Clause", ["redistribution and use in source and binary forms", "neither the name of"]),
    ("BSD-2-Clause", ["redistribution and use in source and binary forms", "this list of conditions and the following disclaimer"]),
    ("MPL-2.0", ["mozilla public license", "version 2.0"]),
    ("ISC", ["permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted"]),
    ("Unlicense", ["this is free and unencumbered software released into the public domain"]),
]

NAME = re.compile(r"^(licen[sc]e|copying)([.-].*)?$", re.I)


def _normalize(text):
    return re.sub(r"\s+", " ", text.replace("“", '"').replace("”", '"')).lower()


def classify(text):
    """The SPDX id of a license text, or "unknown"."""
    t = _normalize(text)
    for spdx, phrases in KNOWN:
        if all(p in t for p in phrases):
            # ISC and 0BSD share their grant; 0BSD lacks ISC's notice condition
            if spdx == "ISC" and "provided that the above copyright notice and this permission notice appear in all copies" not in t:
                return "0BSD"
            return spdx
    return "unknown"


def detect(module_dir):
    """The license files at the module's root: a list of (file name, SPDX id),
    sorted by name. Unreadable or oversized (over 1 MB) files are "unknown"."""
    out = []
    try:
        names = sorted(os.listdir(module_dir))
    except OSError:
        return out
    for name in names:
        p = os.path.join(module_dir, name)
        if not NAME.match(name) or not os.path.isfile(p) or os.path.islink(p):
            continue
        try:
            if os.path.getsize(p) > 1 << 20:
                out.append((name, "unknown"))
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                out.append((name, classify(f.read())))
        except OSError:
            out.append((name, "unknown"))
    return out


def redistributable(found):
    """Whether docs may be shown: at least one recognized license file."""
    return any(spdx != "unknown" for _, spdx in found)
