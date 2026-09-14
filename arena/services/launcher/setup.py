"""Configure hosts for the installed N-Gage Launcher and selected N-Gage 2.0 games."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import yaml
from arena.tools.backups import restore
from arena.tools.hosts import host_target

HOST_SETTINGS = {'WebServicesHostname', 'JabberFQDN', 'GameServerFQDN',
                 'GroupChatFQDN', 'LegalPolicyHostName'}


def configure(data, games, address='127.0.0.1', http_port=8194, reset_login=None):
    data = Path(data).resolve()
    address = host_target(address)
    if not 1 <= http_port <= 65535:
        raise ValueError('Invalid HTTP port')
    if reset_login is not None and not re.fullmatch(r'[A-Za-z0-9_-]+', reset_login):
        raise ValueError('Invalid ROM code')
    updates = {}
    if reset_login:
        repository = data/'drives/c/private/10202be9/persists'/reset_login
        for source in repository.glob('*'):
            if source.name.lower() == '20001077.cre':
                updates[source] = None
    selected = {f'{int(game, 16):08x}' for game in games} | {'2000106c', '20007b39'}
    domains = set()
    for drive in ('c', 'e'):
        for private in (data/'drives'/drive/'private').glob('*'):
            if private.name.lower() not in selected:
                continue
            for source in private.rglob('*'):
                if source.name.lower() != 'config.xml':
                    continue
                original = source.read_bytes().decode('utf-8')
                # Some shipped configurations omit whitespace between XML attributes.
                for name, value in re.findall(r'<nafSetting\s+name="([^"]+)"\s+value="([^"]+)"',
                                              original):
                    value = value.split(':', 1)[0]
                    if name in HOST_SETTINGS and re.fullmatch(r'[A-Za-z0-9.-]+', value) and '.' in value:
                        domains.add(value.lower().rstrip('.'))
                rewritten = re.sub(r'(<nafSetting\s+name="WebServicesHostname"\s+value=")([^":]+)(?::[0-9]+)?(")',
                                   lambda m: m[1]+m[2]+(':'+str(http_port) if http_port != 80 else '')+m[3], original)
                if rewritten != original:
                    updates[source] = rewritten.encode()
    if not domains:
        raise ValueError('No installed N-Gage 2.0 service configuration found')
    for drive in ('c', 'e'):
        repository = data/'drives'/drive/'private/10202be9'
        for source in repository.glob('*'):
            if source.name.lower() not in {'20008bb7.txt', '20008bbb.txt'}:
                continue
            content = source.read_bytes()
            text = content.decode('utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
            for line in text.splitlines():
                fields = line.split(None, 2)
                if len(fields) != 3 or fields[1] != 'string':
                    continue
                url = urlsplit(fields[2].strip().strip('"'))
                ranking = (source.name.lower() == '20008bb7.txt'
                           and re.fullmatch(r'0[xX]0*[bB]', fields[0]) and url.path == '/rankings.html')
                showroom = source.name.lower() == '20008bbb.txt' and url.path.startswith('/sh/output/')
                if url.scheme in ('http', 'https') and url.hostname and (ranking or showroom):
                    domains.add(url.hostname.lower().rstrip('.'))
    config = data/'config.yml'
    settings = yaml.safe_load(config.read_text())
    if not isinstance(settings, dict) or not isinstance(settings.setdefault('hosts', {}), dict):
        raise ValueError('Expected a config mapping with hostname-to-target hosts')
    hosts = settings['hosts']
    previous_hosts = dict(hosts)
    for host in list(hosts):
        if str(host).lower().rstrip('.') in domains:
            del hosts[host]
    hosts.update({host: address for host in sorted(domains)})
    content = yaml.safe_dump(settings, sort_keys=False).encode()
    if hosts != previous_hosts:
        updates[config] = content
    if not updates:
        return None
    backup = data/'arena-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(parents=True)
    files = {}
    for source in updates:
        relative = str(source.relative_to(data))
        destination = backup/relative
        files[relative] = source.exists()
        if source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
    (backup/'manifest.json').write_text(json.dumps({'data': str(data), 'game': 'N-Gage 2.0',
                                                 'files': files}, indent=2)+'\n')
    for source, content in updates.items():
        if content is None:
            source.unlink()
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        temporary = source.with_suffix('.arena-tmp')
        temporary.write_bytes(content)
        temporary.replace(source)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--data', type=Path, help='EKA2L1 Documents/data; stop the emulator first')
    group.add_argument('--restore', type=Path)
    parser.add_argument('--game', action='append', default=[], help='Game UID in hexadecimal; repeat for more games')
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=8194)
    parser.add_argument('--reset-login', metavar='ROM', help='Back up and reset local NAF login preferences for a ROM, e.g. rm-409')
    args = parser.parse_args()
    try:
        if args.restore:
            restore(args.restore)
        else:
            backup = configure(args.data, args.game, args.server, args.http_port, args.reset_login)
            print('Backup:', backup if backup else 'already configured')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Setup failed: {error}\n')


if __name__ == '__main__':
    main()
