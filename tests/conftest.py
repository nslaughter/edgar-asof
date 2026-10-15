"""The guard that keeps every test off the network.

AGENTS.md's rules have tests use local servers and stored versions, never
the network. While tests run, a connection or a datagram to any host but
this one, and a lookup of any name but `localhost`, fails the test that
makes it, or the fixture or collection that does. It fails with
`pytest.fail`, whose error isn't an `Exception`, so the code under test
can't catch it and go on, as a client that retries a failed connection
would. A loopback address and a Unix socket are this host's.

A proxy on this host would take a request for another host and send it
on. So while tests run, the environment names no proxy, and `no_proxy` is
`*`, which also keeps urllib from reading a proxy from macOS's settings: an
HTTP client connects to the host it requests, which the guard checks.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from typing import Any

import pytest

# The socket methods that send to an address they're given, each with where
# the address is among its arguments. `sendmsg` may leave out its address,
# the fourth, and then sends to the peer that `connect` checked, as `send`
# does. Windows has no `sendmsg`.
SENDING = {"connect": 0, "connect_ex": 0, "sendto": -1, "sendmsg": 3}
# The functions that look up a name or an address.
LOOKING_UP = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo")

guard = pytest.MonkeyPatch()


def is_local(host: object) -> bool:
    """Whether a host is this one: `localhost`, or a loopback address."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        # An IPv6 address can end in its zone, as `fe80::1%en0` does.
        return ipaddress.ip_address(host.partition("%")[0]).is_loopback
    except ValueError:
        return False


def refuse(what: str) -> None:
    pytest.fail(
        f"A test reached for the network: {what}. Tests use local servers and stored versions."
    )


def sending(method: Callable[..., Any], at: int) -> Callable[..., Any]:
    """A socket method that refuses an address of another host, its argument `at`."""

    def guarded(self: socket.socket, *args: Any) -> Any:
        try:
            address = args[at]
        except IndexError:
            # No address: `sendmsg` sends to the socket's peer.
            return method(self, *args)
        local = isinstance(address, tuple) and is_local(address[0])
        if self.family != socket.AF_UNIX and not local:
            refuse(f"{method.__name__} to {address!r}")
        return method(self, *args)

    return guarded


def looking_up(function: Callable[..., Any]) -> Callable[..., Any]:
    """A lookup that refuses a name or an address of another host.

    A host of `None` is a lookup of this host's own addresses, which asks
    no server. `getnameinfo` takes an address, whose host comes first.
    """

    def guarded(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host[0] if isinstance(host, tuple) else host
        if name is not None and not is_local(name):
            refuse(f"{function.__name__} of {name!r}")
        return function(host, *args, **kwargs)

    return guarded


def pytest_configure(config: pytest.Config) -> None:
    for name, at in SENDING.items():
        if hasattr(socket.socket, name):
            guard.setattr(socket.socket, name, sending(getattr(socket.socket, name), at))
    for name in LOOKING_UP:
        guard.setattr(socket, name, looking_up(getattr(socket, name)))
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            guard.delenv(name)
    for name in ("no_proxy", "NO_PROXY"):
        guard.setenv(name, "*")


def pytest_unconfigure(config: pytest.Config) -> None:
    guard.undo()
