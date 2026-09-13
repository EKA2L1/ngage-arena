"""Configure an existing EKA2L1 installation for the local Arena service."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct

import yaml

from .guides import decode_links
from .hosts import host_target

DISABLED_GSB = '5e08ad825522685b50b08381f33815b2b441aaecd4950861627374d705cb9c49'
ENABLED_GSB = '4134cc9b01ba9cc19b3815a97964fc1bc744fc1bde77ef0bcc073be8bb839dcd'
REPAIRED_GSB = 'f602a6abe1aa7e33bbe0152ef3925e0cdb144bf4819d67bbfafbf14a0f9d77bf'
ENTRY_OFFSET = 0x2878
MESSAGE_OFFSET = 0x15db4
MESSAGE_ORIGINAL = bytes.fromhex('10402de90040a0e10100a0e10210a0e10320a0e10130a0e302f9ffeb0400a0e1010000eb1040bde81eff2fe1')
MESSAGE_REPAIRED = bytes.fromhex('10402de90040a0e1341080e50100a0e10210a0e10320a0e10130a0e301f9ffeb0400a0e11040bde8ffffffea')


def enable_arena(data):
    if len(data) < 4:
        raise ValueError('GSBAPP.APP is truncated')
    offset, = struct.unpack_from('<I', data, len(data) - 4)
    if not 0 < offset < len(data) - 4:
        raise ValueError('GSBAPP.APP is not a supported compressed launcher')
    payload = gzip.decompress(data[offset:-4])
    digest = hashlib.sha256(payload).hexdigest()
    if digest == REPAIRED_GSB:
        return data
    if digest not in (DISABLED_GSB, ENABLED_GSB):
        raise ValueError('Unknown GSBAPP.APP revision; refusing to patch it')
    if payload[MESSAGE_OFFSET:MESSAGE_OFFSET + len(MESSAGE_ORIGINAL)] != MESSAGE_ORIGINAL:
        raise ValueError('Message cache function does not match the supported revision')
    payload = payload[:ENTRY_OFFSET] + bytes.fromhex('30402de9') + payload[ENTRY_OFFSET + 4:]
    # The sent-message path must retain its cache even before the first inbox download.
    payload = payload[:MESSAGE_OFFSET] + MESSAGE_REPAIRED + payload[MESSAGE_OFFSET + len(MESSAGE_ORIGINAL):]
    if hashlib.sha256(payload).hexdigest() != REPAIRED_GSB:
        raise ValueError('Patched launcher failed verification')
    return data[:offset] + gzip.compress(payload, mtime=0) + data[-4:]


def configure(data, address, guide_links=None):
    data = Path(data).resolve()
    address = host_target(address)
    config = data / 'config.yml'
    game = data / 'drives/e/system/apps/tombraider/gsbapp.app'
    if not game.exists():
        game = next((p for p in game.parent.iterdir() if p.name.lower() == 'gsbapp.app'), game)
    changed_game = enable_arena(game.read_bytes())
    settings = yaml.safe_load(config.read_text())
    if not isinstance(settings, dict):
        raise ValueError('config.yml must contain a YAML mapping')
    hosts = settings.setdefault('hosts', {})
    if not isinstance(hosts, dict):
        raise ValueError('hosts must be a hostname-to-target mapping')
    for host in ('discovery.cng.n-gage.com', 'arena.cng.n-gage.com'):
        for old in list(hosts):
            if str(old).lower().rstrip('.') == host:
                del hosts[old]
        hosts[host] = address
    settings.pop('ngage-server-address', None)
    billing = Path(__file__).resolve().parents[1] / 'assets/abtesrv.dll'
    updates = {
        config: yaml.safe_dump(settings, sort_keys=False).encode(),
        game: changed_game,
        data / 'drives/e/game.id': b'TombRaider 1.0',
        data / 'drives/c/system/libs/abtesrv.dll': billing.read_bytes(),
    }
    if guide_links is not None:
        links = Path(guide_links).read_bytes()
        decode_links(links)
        updates[data / 'drives/c/system/apps/tombraider/adverts.dat'] = links
    changed = {path: content for path, content in updates.items()
               if not path.exists() or path.read_bytes() != content}
    if not changed:
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup = data / 'arena-backups' / stamp
    backup.mkdir(parents=True)
    manifest = {'data': str(data), 'files': {}}
    for path in changed:
        relative = str(path.relative_to(data))
        manifest['files'][relative] = path.exists()
        if path.exists():
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    # The local billing module may add the missing Modem row on first use.
    for path in (data / 'drives/c/system/data').glob('*'):
        if path.name.lower() == 'cdbv2.dat':
            target = backup / path.relative_to(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            manifest['commdb_backup'] = str(path.relative_to(data))
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path, content in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.arena-tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, help='EKA2L1 Documents/data directory; stop the emulator first')
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--guide-links', type=Path, help='Install an authored adverts.dat room-to-guide mapping')
    parser.add_argument('--restore', type=Path, help='Restore a setup backup directory; stop the emulator first')
    args = parser.parse_args()
    if bool(args.data) == bool(args.restore):
        parser.error('Specify exactly one of --data or --restore')
    if args.restore and args.guide_links:
        parser.error('--guide-links requires --data')
    try:
        if args.restore:
            restore(args.restore)
            print('Arena setup backup restored.')
            return
        backup = configure(args.data, args.server, args.guide_links)
    except (OSError, ValueError, gzip.BadGzipFile) as error:
        parser.exit(1, f'Setup failed: {error}\n')
    print(f'Arena configured. Backups: {backup}' if backup else 'Arena is already configured.')


def restore(backup):
    backup = Path(backup).resolve()
    if backup.parent.name != 'arena-backups':
        raise ValueError('Expected an arena-backups/<timestamp> directory')
    data = backup.parent.parent
    manifest = json.loads((backup / 'manifest.json').read_text())
    files = dict(manifest['files'])
    if 'commdb_backup' in manifest:
        files[manifest['commdb_backup']] = True
    updates = []
    for relative, existed in files.items():
        path = (data / relative).resolve()
        source = (backup / relative).resolve()
        if not path.is_relative_to(data) or not source.is_relative_to(backup):
            raise ValueError('Invalid backup path')
        updates.append((path, source.read_bytes() if existed else None))
    for path, content in updates:
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.arena-tmp')
            temporary.write_bytes(content)
            temporary.replace(path)


if __name__ == '__main__':
    main()
