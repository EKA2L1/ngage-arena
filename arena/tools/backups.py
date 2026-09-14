"""Restore reversible emulator configuration backups."""
import json
from pathlib import Path


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
