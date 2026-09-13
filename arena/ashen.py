"""Compatibility entry point for the shared Arena Community service."""
import argparse
import asyncio
import logging
from pathlib import Path
import time
from arena.accounts import AccountStore
from arena.community import CommunityServer, SOAP
from arena.games.ashen import ScoreStore
from arena.runtime import default_games, serve_community as serve


class AshenStore(AccountStore):
    def __init__(self, directory):
        super().__init__(directory)
        self.scores = ScoreStore(self.db)

    def submit_scores(self, user, scores):
        return self.scores.submit_scores(user, scores)

    def rankings(self, stat, limit):
        return self.scores.rankings(stat, limit)


class AshenServer(CommunityServer):
    def __init__(self, store, trace=None, clock=time.monotonic):
        super().__init__(store, default_games(store), trace, clock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=8192)
    parser.add_argument('--xmpp-port', type=int, default=5222)
    parser.add_argument('--snap-port', type=int, help='Enable High Seize SNAP UDP rooms and battles')
    parser.add_argument('--snap-address', help='IPv4 address advertised to SNAP clients')
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--trace', type=Path, help='Write redacted protocol diagnostics')
    parser.add_argument('--log-level', choices=('INFO', 'DEBUG'), default='INFO')
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format='%(asctime)s %(message)s')
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
