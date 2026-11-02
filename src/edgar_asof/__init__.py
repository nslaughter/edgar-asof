"""What a company reported to the SEC, as it was known at any past time.

Data read by this library comes from the U.S. Securities and Exchange
Commission's EDGAR system. The specifications in spec/ govern the package.
"""

from edgar_asof._errors import (
    BodyNotGivenError,
    CacheError,
    FetchError,
    ForbiddenError,
    NoUserAgentError,
    ReadError,
    SnapshotStoreError,
)
from edgar_asof._read import Bodies, Body, BodyRef, Cache, Source, read_body
from edgar_asof._times import Interpreter, RawTime, header_in_zone, submissions_utc

__all__ = [
    "Bodies",
    "Body",
    "BodyNotGivenError",
    "BodyRef",
    "Cache",
    "CacheError",
    "FetchError",
    "ForbiddenError",
    "Interpreter",
    "NoUserAgentError",
    "RawTime",
    "ReadError",
    "SnapshotStoreError",
    "Source",
    "header_in_zone",
    "read_body",
    "submissions_utc",
]
