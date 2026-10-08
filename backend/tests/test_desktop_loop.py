import asyncio
import socket
import struct
import sys

import pytest

from app.desktop_loop import new_event_loop


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows accept completion race')
def test_connection_accepted_during_server_close_is_closed_without_transport_error():
    errors = []

    async def exercise():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        accepted = asyncio.Event()

        def protocol_factory():
            # Deterministic ordering: accept has completed, construction has
            # not started. This was the failing shutdown callback in the EXE.
            server.close()
            accepted.set()
            return asyncio.Protocol()

        server = await loop.create_server(protocol_factory, '127.0.0.1', 0)
        address = server.sockets[0].getsockname()
        client = socket.socket()
        client.setblocking(False)
        try:
            await loop.sock_connect(client, address)
            await asyncio.wait_for(accepted.wait(), 2)
            assert await asyncio.wait_for(loop.sock_recv(client, 1), 2) == b''
            await asyncio.wait_for(server.wait_closed(), 2)
        finally:
            client.close()
            server.close()

    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(exercise())
    assert errors == []


def test_normal_connection_and_reply_still_work():
    async def exercise():
        async def respond(reader, writer):
            data = await reader.readexactly(4)
            writer.write(data.upper())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(respond, '127.0.0.1', 0)
        try:
            reader, writer = await asyncio.open_connection(*server.sockets[0].getsockname())
            writer.write(b'ping')
            await writer.drain()
            assert await reader.read() == b'PING'
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(exercise())


@pytest.mark.skipif(sys.platform != 'win32', reason='Winsock reset during shutdown')
def test_reset_peer_during_transport_close_releases_server_without_loop_errors(monkeypatch):
    errors = []
    accepted_handles = set()
    original_shutdown = socket.socket.shutdown

    def reset_at_shutdown(sock, how):
        if sock.fileno() in accepted_handles and how == socket.SHUT_RDWR:
            # Force the exact Winsock failure seen in the installed EXE,
            # independently of when Windows delivers the real client reset.
            raise ConnectionResetError(10054, 'peer disappeared during close')
        return original_shutdown(sock, how)

    monkeypatch.setattr(socket.socket, 'shutdown', reset_at_shutdown)

    async def exercise():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        ready = asyncio.Event()
        transports = []

        class PausedClient(asyncio.Protocol):
            def connection_made(self, transport):
                # WebView2 can disappear while the transport is being closed,
                # before a pending receive has consumed the reset notification.
                transport.pause_reading()
                transports.append(transport)
                accepted_handles.add(transport.get_extra_info('socket').fileno())
                ready.set()

        server = await loop.create_server(PausedClient, '127.0.0.1', 0)
        client = socket.socket()
        client.setblocking(False)
        try:
            await loop.sock_connect(client, server.sockets[0].getsockname())
            await asyncio.wait_for(ready.wait(), 2)
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('hh', 1, 0))
            client.close()
            await asyncio.sleep(.03)
            transports[0].close()
            server.close()
            await asyncio.wait_for(server.wait_closed(), 2)
        finally:
            client.close()
            server.close()
            for transport in transports:
                transport.abort()

    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(exercise())
    assert errors == []


@pytest.mark.skipif(sys.platform != 'win32', reason='Desktop Proactor transport')
def test_protocol_callback_failure_remains_visible_to_loop_error_handler():
    errors = []
    failure = RuntimeError('protocol callback failed')

    async def exercise():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        disconnected = asyncio.Event()

        class FailedProtocol(asyncio.Protocol):
            def connection_lost(self, exc):
                disconnected.set()
                raise failure

        server = await loop.create_server(FailedProtocol, '127.0.0.1', 0)
        reader, writer = await asyncio.open_connection(*server.sockets[0].getsockname())
        writer.close()
        await writer.wait_closed()
        try:
            await asyncio.wait_for(disconnected.wait(), 2)
            server.close()
            await asyncio.wait_for(server.wait_closed(), 2)
        finally:
            server.close()

    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(exercise())
    assert any(context.get('exception') is failure for context in errors)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows asynchronous skill/local-model subprocess')
def test_desktop_loop_preserves_async_subprocess_support():
    async def exercise():
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', "print('local worker ready')", stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == 0
        assert output.strip() == b'local worker ready'

    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(exercise())
