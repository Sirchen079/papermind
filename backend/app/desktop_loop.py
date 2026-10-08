"""Keep Windows desktop HTTP transports able to finish shutdown.

CPython issue 109564: accept may complete just before Server.close(), leaving
its scheduled transport construction to run after the server has closed.
Scope the workaround to the desktop's loop; never suppress loop exceptions or
change the application's global asyncio policy.

CPython 3.12 also calls socket.shutdown() before closing and detaching a
transport. A reset WebView2 peer can raise WinError 10054 there, interrupting
cleanup and leaving Server.wait_closed() pending. Normalize only that expected
reset on an accepted socket's final SHUT_RDWR; reuse asyncio's own transport
cleanup so protocol failures and other socket errors remain visible.
"""
import asyncio
import socket
import sys


if sys.platform == 'win32':
    class _DesktopAcceptedSocket(socket.socket):
        def shutdown(self, how):
            try:
                return super().shutdown(how)
            except ConnectionResetError:
                if how != socket.SHUT_RDWR:
                    raise

    class DesktopProactorEventLoop(asyncio.ProactorEventLoop):
        def _make_socket_transport(self, sock, protocol, waiter=None, *, extra=None, server=None):
            if server is not None and not server.is_serving():
                # This is a newly accepted socket, not an established request.
                # Closing it before construction avoids an orphaned transport.
                sock.close()
                return None
            if server is not None:
                family, kind, proto, timeout = sock.family, sock.type, sock.proto, sock.gettimeout()
                handle = sock.detach()
                try:
                    sock = _DesktopAcceptedSocket(family, kind, proto, fileno=handle)
                except BaseException:
                    socket.close(handle)
                    raise
                sock.settimeout(timeout)
            return super()._make_socket_transport(sock, protocol, waiter, extra=extra, server=server)


def new_event_loop():
    return DesktopProactorEventLoop() if sys.platform == 'win32' else asyncio.new_event_loop()
