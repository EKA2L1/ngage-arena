"""Configure the installed High Seize Arena framework without modifying game binaries."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import yaml

from arena.tools.hosts import host_target
from arena.tools.backups import restore


def framework_config(data):
    for drive in ('e', 'c'):
        path = data / 'drives' / drive
        for part in ('system', 'libs', 'framework', 'arena.amr'):
            if not path.is_dir():
                break
            path = next((p for p in path.iterdir() if p.name.lower() == part), path / part)
        if path.is_file():
            return path
    raise ValueError('No installed High Seize Arena framework configuration found')


def configure(data, address='127.0.0.1', http_port=8193):
    data = Path(data).resolve()
    address = host_target(address)
    if not isinstance(http_port, int) or not 1 <= http_port <= 65535:
        raise ValueError('Invalid HTTP port')
    source = framework_config(data)
    original = source.read_text()
    try:
        root = ET.fromstring(original)
    except ET.ParseError as error:
        raise ValueError('Invalid Arena framework XML') from error
    servers = root.find('servers')
    if root.get('app_id') != 'NgageFramework' or servers is None or servers.get('WebServicesProtocol') != 'http://':
        raise ValueError('Unsupported Arena framework configuration')
    replacements = {}
    domains = set()
    for name in ('WebServicesHostname', 'JabberFQDN', 'GameServerFQDN'):
        value = servers.get(name, '')
        parsed = urlsplit('http://' + value)
        if not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('Invalid Arena server hostname')
        parsed.port
        host = host_target(parsed.hostname)
        domains.add(host)
        authority = f'[{host}]' if ':' in host else host
        if name == 'WebServicesHostname':
            replacements[name] = authority + (f':{http_port}' if http_port != 80 else '')
    for name in ('UpdateURL', 'UploadURL', 'DownloadURL'):
        value = servers.get(name)
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid Arena HTTP URL')
        parsed.port
        host = host_target(parsed.hostname)
        domains.add(host)
        authority = f'[{host}]' if ':' in host else host
        replacements[name] = urlunsplit(parsed._replace(netloc=authority + (f':{http_port}' if http_port != 80 else '')))
    rewritten = original
    for name, value in replacements.items():
        rewritten, count = re.subn(r'\b' + name + r'\s*=\s*([\'"])[^\'"]*\1',
                                  lambda m: name + '=' + m[1] + value + m[1], rewritten)
        if count != 1:
            raise ValueError('Ambiguous Arena server configuration')
    config = data / 'config.yml'
    settings = yaml.safe_load(config.read_text())
    if not isinstance(settings, dict) or not isinstance(settings.setdefault('hosts', {}), dict):
        raise ValueError('Expected a config mapping with hostname-to-target hosts')
    hosts = settings['hosts']
    previous = dict(hosts)
    for host in list(hosts):
        if str(host).strip().lower().removesuffix('.') in domains:
            del hosts[host]
    hosts.update({host: address for host in sorted(domains)})
    updates = {}
    if rewritten != original:
        updates[source] = rewritten.encode()
    if hosts != previous:
        updates[config] = yaml.safe_dump(settings, sort_keys=False).encode()
    if not updates:
        return None
    backup = data / 'arena-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(parents=True)
    files = {}
    for path in updates:
        relative = str(path.relative_to(data))
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        files[relative] = True
    (backup / 'manifest.json').write_text(json.dumps({'game': 'High Seize', 'files': files}, indent=2) + '\n')
    for path, content in updates.items():
        temporary = path.with_name(path.name + '.arena-tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--data', type=Path, help='EKA2L1 Documents/data; stop the emulator first')
    group.add_argument('--restore', type=Path)
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=8193)
    args = parser.parse_args()
    try:
        if args.restore:
            restore(args.restore)
            print('High Seize setup restored.')
        else:
            backup = configure(args.data, args.server, args.http_port)
            print(f'High Seize configured. Backup: {backup}' if backup else 'High Seize is already configured.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Setup failed: {error}\n')


if __name__ == '__main__':
    main()
