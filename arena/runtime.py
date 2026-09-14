"""Composition root: protocol listeners and independently registered games."""
import argparse
import asyncio
import logging
from pathlib import Path
from arena.services.accounts.store import AccountStore
from arena.services.community.server import CommunityServer
from arena.games import GameRegistry
from arena.games.ashen.game import AshenGame
from arena.games.high_seize.game import HighSeizeGame
from arena.games.hooked.game import HookedGame

LOG = logging.getLogger(__name__)


def default_games(accounts):
    return GameRegistry([AshenGame(accounts), HighSeizeGame(accounts), HookedGame(accounts)])


async def serve_community(args):
    from arena.services.snap.protocol import SnapServer
    store = AccountStore(args.data)
    games = default_games(store)
    server = CommunityServer(store, games, args.trace,
                             local_native_http=getattr(args, 'local_native_http', False))
    listeners = []
    datagrams = []
    tomb = None
    try:
        tls_ports = set(getattr(args, 'tls_port', None) or [])
        if tls_ports:
            from arena.services.community.tls import CommunityListener, server_context
            context = server_context(args.tls_cert, args.tls_key, args.legacy_tls)
            for port in tls_ports:
                listeners.append(CommunityListener(server.http, args.host, port, context))
            LOG.info('Community HTTP/HTTPS listening on %s:%s', args.host, sorted(tls_ports))
        for port in set(args.http_port if isinstance(args.http_port, list) else [args.http_port]):
            if port not in tls_ports:
                listeners.append(await asyncio.start_server(server.http, args.host, port))
        listeners.append(await asyncio.start_server(server.xmpp, args.host, args.xmpp_port))
        if args.snap_port is not None:
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: SnapServer(server.snap_credentials, args.snap_address or args.host,
                                   application=games.games['36280'].application()),
                local_addr=(args.host, args.snap_port))
            datagrams.append(transport)
            LOG.info('SNAP UDP listening on %s:%d', args.host, args.snap_port)
        if getattr(args, 'airplay_port', 0):
            from arena.games.tomb_raider.server import Arena
            from arena.games.tomb_raider.store import Store
            tomb = Store(args.data, accounts=store)
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: Arena(tomb, args.billing), local_addr=(args.host, args.airplay_port))
            datagrams.append(transport)
            LOG.info('AirPlay UDP listening on %s:%d', args.host, args.airplay_port)
        LOG.info('Community listening on %s: HTTP %s, XMPP %d', args.host, args.http_port, args.xmpp_port)
        await asyncio.gather(*(listener.serve_forever() for listener in listeners))
    finally:
        for transport in datagrams:
            transport.close()
        for listener in listeners:
            listener.close()
            await listener.wait_closed()
        await server.close()
        if tomb:
            tomb.close()
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, action='append', help='Repeat for each legacy Community port (default: 8192, 8193 and 8194)')
    parser.add_argument('--tls-port', type=int, action='append', help='Accept both HTTP and HTTPS on this port')
    parser.add_argument('--tls-cert', type=Path)
    parser.add_argument('--tls-key', type=Path)
    parser.add_argument('--legacy-tls', action='store_true', help='Allow N-Gage 2.0 TLS 1.0 RSA/AES clients')
    parser.add_argument('--local-native-http', action='store_true',
                        help='Allow credential-free native rankings and achievements from loopback clients with an active SNAP login; trusts local processes')
    parser.add_argument('--xmpp-port', type=int, default=5222)
    parser.add_argument('--snap-port', type=int, default=9090)
    parser.add_argument('--snap-address')
    parser.add_argument('--airplay-port', type=int, default=41001, help='Tomb Raider UDP port; 0 disables this listener')
    parser.add_argument('--billing', type=Path, default=Path(__file__).resolve().parent/'games/tomb_raider/assets/abtesrv.dll')
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--log-level', choices=('INFO', 'DEBUG'), default='INFO')
    args = parser.parse_args()
    if args.tls_port and (not args.tls_cert or not args.tls_key):
        parser.error('--tls-port requires --tls-cert and --tls-key')
    args.http_port = args.http_port or [8192, 8193, 8194]
    logging.basicConfig(level=args.log_level, format='%(asctime)s %(message)s')
    try:
        asyncio.run(serve_community(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
