"""The guard in conftest.py fails any test that reaches the network.

Each case runs a test under a copy of the guard, in a pytest of its own,
through pytester, so that the test the guard fails isn't one of these.
Under a test that the guard should stop, the network is replaced by
stand-ins that reach nothing, so that even a guard that lets the test
through sends nothing. The addresses are reserved besides: 192.0.2.1 is
for documentation (RFC 5737), and a name in `.invalid` never resolves
(RFC 6761).
"""

from __future__ import annotations

import socket
import textwrap
from pathlib import Path
from typing import Any

import pytest

GUARD = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")

# Each reaches for the network, and catches any Exception, as a client that
# retries a failed connection would.
REACHING = {
    "connect": "with socket.socket() as s: s.connect(('192.0.2.1', 443))",
    "connect_ex": "with socket.socket() as s: s.connect_ex(('192.0.2.1', 443))",
    "sendto": "with socket.socket(type=socket.SOCK_DGRAM) as s: s.sendto(b'', ('192.0.2.1', 53))",
    "sendmsg": (
        "with socket.socket(type=socket.SOCK_DGRAM) as s:"
        " s.sendmsg([b''], [], 0, ('192.0.2.1', 53))"
    ),
    "getaddrinfo": "socket.getaddrinfo('edgar-asof.invalid', 443)",
    "gethostbyname": "socket.gethostbyname('edgar-asof.invalid')",
    "gethostbyname_ex": "socket.gethostbyname_ex('edgar-asof.invalid')",
    "gethostbyaddr": "socket.gethostbyaddr('192.0.2.1')",
    "getnameinfo": "socket.getnameinfo(('192.0.2.1', 443), 0)",
    "an HTTP client": "urllib.request.urlopen('https://edgar-asof.invalid/', timeout=1)",
}


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stand-ins for the network beneath the guard, and what reached them."""
    reached: list[str] = []

    def stand_in(name: str) -> Any:
        def reach(*args: Any, **kwargs: Any) -> Any:
            reached.append(name)
            raise OSError(f"{name}: tests have no network")

        reach.__name__ = name
        return reach

    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        monkeypatch.setattr(socket.socket, name, stand_in(name))
    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
    ):
        monkeypatch.setattr(socket, name, stand_in(name))
    return reached


def run(pytester: pytest.Pytester, source: str) -> pytest.RunResult:
    pytester.makeconftest(GUARD)
    pytester.makepyfile(textwrap.dedent(source))
    return pytester.runpytest()


@pytest.mark.parametrize("action", list(REACHING.values()), ids=list(REACHING))
def test_a_test_that_reaches_the_network_fails_though_it_catches_the_error(
    pytester: pytest.Pytester, offline: list[str], action: str
) -> None:
    result = run(
        pytester,
        f"""
        import socket
        import urllib.request

        def test_reaches():
            try:
                {action}
            except Exception:
                pass
        """,
    )

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*A test reached for the network*"])
    assert offline == []


def test_a_fixture_that_reaches_the_network_fails_its_test(
    pytester: pytest.Pytester, offline: list[str]
) -> None:
    result = run(
        pytester,
        """
        import socket

        import pytest

        @pytest.fixture
        def reaching():
            try:
                socket.getaddrinfo("edgar-asof.invalid", 443)
            except Exception:
                pass

        def test_uses(reaching):
            pass
        """,
    )

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*A test reached for the network*"])
    assert offline == []


def test_a_test_may_reach_this_host(pytester: pytest.Pytester) -> None:
    result = run(
        pytester,
        """
        import socket

        def test_own_addresses():
            socket.getaddrinfo(None, 80, flags=socket.AI_PASSIVE)

        def test_loopback():
            with socket.create_server(("127.0.0.1", 0)) as server:
                port = server.getsockname()[1]
                for host in ("127.0.0.1", "localhost"):
                    with socket.create_connection((host, port)):
                        pass

        def test_datagrams():
            with socket.socket(type=socket.SOCK_DGRAM) as server:
                server.bind(("127.0.0.1", 0))
                address = server.getsockname()
                with socket.socket(type=socket.SOCK_DGRAM) as client:
                    client.sendto(b"", address)
                    client.sendmsg([b""], [], 0, address)
                    client.connect(address)
                    client.sendmsg([b""])

        def test_unix_socket():
            with socket.socket(socket.AF_UNIX) as server:
                server.bind("guard.sock")
                server.listen()
                with socket.socket(socket.AF_UNIX) as client:
                    client.connect("guard.sock")
        """,
    )

    result.assert_outcomes(passed=4)
