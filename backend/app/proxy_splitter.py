"""A local proxy that sends *some* traffic upstream and the rest direct.

The community API binds a session to the address that solved the captcha, so
the engine's signed requests have to leave through the same residential proxy
the browser used. Track downloads do not — and they are three orders of
magnitude larger, so paying a per-gigabyte proxy to carry FLACs is what makes
the whole arrangement uneconomic.

Pointing the engine here instead splits the difference:

    engine --HTTPS_PROXY--> splitter --+-- community API --> residential proxy
                                       +-- everything else -> direct

``PROXY_HOSTS`` lists the host suffixes that go upstream. Leave it empty and
nothing does: every connection is made directly and simply *logged*, which is
how you discover what the engine actually talks to and what each host costs.
Read the log, fill in the list, and from then on only the small signed calls
are metered.

Deliberately dependency-free and deliberately fail-open: any error routing a
connection falls back to a direct one, because a broken proxy here would take
downloads down with it.
"""
from __future__ import annotations

import base64
import logging
import os
import select
import socket
import threading
import urllib.parse

log = logging.getLogger(__name__)

#: Give up on a stalled tunnel rather than leaking a thread per download.
_IDLE_TIMEOUT = 300.0
_CONNECT_TIMEOUT = 30.0
_HEADER_LIMIT = 64 * 1024


def host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    """Does ``host`` fall under one of ``suffixes``?

    ``example.com`` matches itself and ``api.example.com``, but not
    ``notexample.com`` — the boundary is a dot, not a substring.
    """
    host = host.lower().rsplit(":", 1)[0].strip(".")
    for suffix in suffixes:
        suffix = suffix.lower().strip().strip(".")
        if suffix and (host == suffix or host.endswith("." + suffix)):
            return True
    return False


def _pump(a: socket.socket, b: socket.socket) -> int:
    """Shuttle bytes both ways until either side closes. Returns bytes moved."""
    total = 0
    sockets = [a, b]
    while True:
        try:
            readable, _, errored = select.select(sockets, [], sockets, _IDLE_TIMEOUT)
        except (OSError, ValueError):
            break
        if errored or not readable:
            break
        for source in readable:
            target = b if source is a else a
            try:
                chunk = source.recv(65536)
            except OSError:
                return total
            if not chunk:
                return total
            total += len(chunk)
            try:
                target.sendall(chunk)
            except OSError:
                return total
    return total


class SplittingProxy:
    """HTTP proxy that routes per-host. Serves loopback only."""

    def __init__(
        self,
        port: int,
        upstream: str | None,
        upstream_hosts: tuple[str, ...],
    ) -> None:
        self.port = port
        self.upstream_hosts = upstream_hosts
        self._upstream = self._parse_upstream(upstream)
        self._server: socket.socket | None = None

    @staticmethod
    def _parse_upstream(upstream: str | None) -> tuple[str, int, str | None] | None:
        if not upstream:
            return None
        parsed = urllib.parse.urlparse(upstream)
        if not parsed.hostname:
            return None
        auth = None
        if parsed.username:
            raw = f"{urllib.parse.unquote(parsed.username)}:" \
                  f"{urllib.parse.unquote(parsed.password or '')}"
            auth = base64.b64encode(raw.encode()).decode()
        return parsed.hostname, parsed.port or 8080, auth

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Bind and serve in a daemon thread.

        ``False`` means the port is already taken — which normally means
        another process in this container is already serving it, and pointing
        the engine at that one is exactly right.
        """
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # POSIX: lets us rebind through TIME_WAIT after a restart, while
            # still refusing a port something is actively listening on — which
            # is the signal we rely on to detect an existing instance. Windows
            # reads the same flag as permission to take over a live socket, so
            # it must not be set there.
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self.port))
        except OSError:
            server.close()
            return False
        server.listen(64)
        self._server = server
        threading.Thread(target=self._serve, daemon=True).start()

        if self.upstream_hosts and self._upstream:
            log.info(
                "split proxy on 127.0.0.1:%d — %s go via %s, everything else direct",
                self.port, ", ".join(self.upstream_hosts), self._upstream[0],
            )
        else:
            log.warning(
                "split proxy on 127.0.0.1:%d in LOG-ONLY mode: every connection "
                "goes direct. Set PROXY_HOSTS once the log shows which hosts "
                "need the residential exit.",
                self.port,
            )
        return True

    def _serve(self) -> None:
        assert self._server is not None
        while True:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    # -- one connection ----------------------------------------------------

    def _handle(self, client: socket.socket) -> None:
        upstream_socket = None
        try:
            header = self._read_header(client)
            if not header:
                return
            request_line = header.split(b"\r\n", 1)[0].decode("latin-1")
            method, target, _, *_ = (*request_line.split(" "), "", "")

            if method.upper() == "CONNECT":
                host, _, port = target.partition(":")
                port = int(port or 443)
            else:
                parsed = urllib.parse.urlparse(target)
                host = parsed.hostname or ""
                port = parsed.port or 80
            if not host:
                return

            via_upstream = bool(self._upstream) and host_matches(host, self.upstream_hosts)
            upstream_socket = self._connect(host, port, header, method, via_upstream, client)
            if upstream_socket is None:
                return

            moved = _pump(client, upstream_socket)
            log.info(
                "%s %s:%d — %.1f KB", "PROXIED " if via_upstream else "direct  ",
                host, port, moved / 1024,
            )
        except Exception as exc:
            log.debug("split proxy connection failed: %s", exc)
        finally:
            for sock in (client, upstream_socket):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

    @staticmethod
    def _read_header(client: socket.socket) -> bytes:
        client.settimeout(_CONNECT_TIMEOUT)
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = client.recv(4096)
            if not chunk:
                return b""
            buffer += chunk
            if len(buffer) > _HEADER_LIMIT:
                return b""
        return buffer

    def _connect(
        self,
        host: str,
        port: int,
        header: bytes,
        method: str,
        via_upstream: bool,
        client: socket.socket,
    ) -> socket.socket | None:
        """Open the far side, doing whichever handshake the route needs.

        An upstream failure falls back to a direct connection: losing the
        residential exit costs a 401 on one request, whereas failing the
        connection outright costs the whole download.
        """
        if via_upstream and self._upstream:
            try:
                return self._connect_via_upstream(host, port, header, method, client)
            except Exception as exc:
                log.warning("upstream proxy failed for %s (%s); going direct", host, exc)

        remote = socket.create_connection((host, port), _CONNECT_TIMEOUT)
        remote.settimeout(None)
        client.settimeout(None)
        if method.upper() == "CONNECT":
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            client.sendall(b"")  # nothing to acknowledge; forward the request
            remote.sendall(header)
        return remote

    def _connect_via_upstream(
        self,
        host: str,
        port: int,
        header: bytes,
        method: str,
        client: socket.socket,
    ) -> socket.socket:
        assert self._upstream is not None
        up_host, up_port, auth = self._upstream
        remote = socket.create_connection((up_host, up_port), _CONNECT_TIMEOUT)

        if method.upper() == "CONNECT":
            request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if auth:
                request += f"Proxy-Authorization: Basic {auth}\r\n"
            remote.sendall((request + "\r\n").encode("latin-1"))

            remote.settimeout(_CONNECT_TIMEOUT)
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = remote.recv(4096)
                if not chunk:
                    raise OSError("upstream closed during CONNECT")
                response += chunk
            status = response.split(b" ", 2)[1:2]
            if status and not status[0].startswith(b"2"):
                raise OSError(f"upstream refused CONNECT: {response[:80]!r}")
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            # Absolute-form request forwarded as-is, with credentials added.
            if auth:
                head, _, rest = header.partition(b"\r\n")
                header = head + f"\r\nProxy-Authorization: Basic {auth}".encode() \
                    + b"\r\n" + rest
            remote.sendall(header)

        remote.settimeout(None)
        client.settimeout(None)
        return remote


_instance: SplittingProxy | None = None
_lock = threading.Lock()


def ensure_running(port: int, upstream: str | None, hosts: tuple[str, ...]) -> str:
    """Start the splitter once per process; return the URL to point a proxy at.

    A second process in the same container finds the port taken and simply
    uses the instance that is already there — which is what we want, since
    both the server's job runs and a manual ``verify_cli`` need the same one.
    """
    global _instance
    with _lock:
        if _instance is None:
            candidate = SplittingProxy(port, upstream, hosts)
            if candidate.start():
                _instance = candidate
            else:
                log.debug("split proxy port %d already served; reusing it", port)
    return f"http://127.0.0.1:{port}"
