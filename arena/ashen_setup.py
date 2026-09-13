"""Configure Ashen's Arena host mappings without changing game files."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import yaml

from .setup import restore

HOSTS = ('arena.n-gage.com', 'im01.ashen.torus.sf.yav4.com')


def configure(data, address='127.0.0.1'):
    data = Path(data).resolve()
    from arena.hosts import host_target
    address = host_target(address)
    config = data / 'config.yml'
    settings = yaml.safe_load(config.read_text())
    if not isinstance(settings, dict):
        raise ValueError('config.yml must contain a YAML mapping')
    hosts = settings.setdefault('hosts', {})
    if not isinstance(hosts, dict):
        raise ValueError('hosts must be a hostname-to-address mapping')
    for host in HOSTS:
        for old in list(hosts):
            if str(old).strip().lower().removesuffix('.') == host:
                del hosts[old]
        hosts[host] = address
    updates = {config: yaml.safe_dump(settings, sort_keys=False).encode()}
    changed = {p: b for p, b in updates.items() if p.read_bytes() != b}
    if not changed:
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup = data / 'arena-backups' / stamp
    backup.mkdir(parents=True)
    manifest = {'data': str(data), 'game': 'Ashen', 'files': {}}
    for path in changed:
        relative = str(path.relative_to(data))
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        manifest['files'][relative] = True
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path, content in changed.items():
        temporary = path.with_name(path.name + '.arena-tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--data', type=Path, help='EKA2L1 Documents/data; stop the emulator first')
    group.add_argument('--restore', type=Path, help='Restore a setup backup; stop the emulator first')
    parser.add_argument('--server', default='127.0.0.1')
    args = parser.parse_args()
    try:
        if args.restore:
            restore(args.restore)
            print('Ashen setup restored.')
        else:
            backup = configure(args.data, args.server)
            print(f'Ashen configured. Backup: {backup}' if backup else 'Ashen is already configured.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Setup failed: {error}\n')


if __name__ == '__main__':
    main()
