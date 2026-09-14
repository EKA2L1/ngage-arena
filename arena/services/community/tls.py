"""Community listener for clients that share one port for HTTP and HTTPS."""
import asyncio
import logging
import socket
import ssl
import warnings

LOG = logging.getLogger(__name__)


def server_context(cert, key, legacy=False):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    if legacy:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            context.minimum_version = ssl.TLSVersion.TLSv1
        context.set_ciphers('AES256-SHA:AES128-SHA:@SECLEVEL=0')
    return context


class CommunityListener:
    def __init__(self, handler, host, port, context, timeout=20):
        self.handler = handler
        self.context = context
        self.timeout = timeout
        self.socket = socket.create_server((host, port))
        self.socket.setblocking(False)
        self.tasks = set()
        self.accept_task = None

    async def serve_forever(self):
        self.accept_task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        try:
            while True:
                client, _ = await loop.sock_accept(self.socket)
                if len(self.tasks) >= 128:
                    client.close()
                    continue
                task = asyncio.create_task(self.accept(client))
                self.tasks.add(task)
                task.add_done_callback(lambda done, client=client: (self.tasks.discard(done), client.close()))
        finally:
            self.socket.close()

    async def accept(self, client):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        writer = None
        try:
            ready = loop.create_future()

            def readable():
                if not ready.done():
                    ready.set_result(None)

            loop.add_reader(client.fileno(), readable)
            try:
                await asyncio.wait_for(ready, self.timeout)
            finally:
                loop.remove_reader(client.fileno())
            # Leave ClientHello in the socket for the standard SSL transport.
            first = client.recv(1, socket.MSG_PEEK)
            if not first:
                return
            context = self.context if first == b'\x16' else None
            protocol = asyncio.StreamReaderProtocol(reader)
            options = {'ssl': context, 'ssl_handshake_timeout': self.timeout} if context else {}
            transport, _ = await loop.connect_accepted_socket(lambda: protocol, client, **options)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            if context:
                LOG.debug('Community TLS %s %s', writer.get_extra_info('ssl_object').version(),
                          writer.get_extra_info('cipher')[0])
            await self.handler(reader, writer)
        except (OSError, TimeoutError) as error:
            LOG.info('Community connection closed: %s', error)
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError, TimeoutError):
                    pass
            else:
                client.close()

    def close(self):
        if self.accept_task:
            self.accept_task.cancel()
        self.socket.close()
        for task in self.tasks:
            task.cancel()

    async def wait_closed(self):
        await asyncio.gather(*self.tasks, return_exceptions=True)
