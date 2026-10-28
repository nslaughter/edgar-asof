"""The feeds the library reads, and the form of each one's URLs.

fetching.md's §5 gives them. A URL of none of them is one that CLIENT-1
doesn't allow. In a `companyfacts` URL and a filing header's, a CIK is an
integer from 1 to 9,999,999,999, as facts.md's FACT-1 gives it: in ten
digits with leading zeros in the first, and without them in the second. A
`submissions` URL takes any single path segment, as §5 gives it for the
further files, so its CIK isn't checked.
"""

from __future__ import annotations

import re

FEEDS = {
    # The company's list, `CIK##########.json`, and the further files it
    # names: any single path segment, other than `.` and `..`.
    "submissions": re.compile(r"https://data\.sec\.gov/submissions/(?!\.\.?\Z)[^/?#]+"),
    "companyfacts": re.compile(
        r"https://data\.sec\.gov/api/xbrl/companyfacts/CIK(?!0{10})[0-9]{10}\.json"
    ),
    # A filing's header, under its company's CIK and its accession number,
    # without dashes and then with them.
    "filings": re.compile(
        r"https://www\.sec\.gov/Archives/edgar/data/[1-9][0-9]{0,9}/(?P<accession>[0-9]{18})/"
        r"(?P<dashed>[0-9]{10}-[0-9]{2}-[0-9]{6})-index-headers\.html"
    ),
}


def feed(url: str) -> str:
    """The feed a URL belongs to.

    Raises ValueError for a URL of none of them (READ-4).
    """
    for name, form in FEEDS.items():
        match = form.fullmatch(url)
        if match is None:
            continue
        if name == "filings" and match["accession"] != match["dashed"].replace("-", ""):
            break
        return name
    raise ValueError(f"not a URL of a feed that edgar-asof reads: {url!r}")
