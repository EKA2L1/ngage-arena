# High Seize setup

Use the original multilingual 1.0.2 package. With EKA2L1 stopped, run from the repository root:

```sh
.venv/bin/python -m arena.games.high_seize.setup --data /absolute/path/to/Documents/data
```

This backs up and edits host mappings and the Arena framework XML HTTP endpoint (default 8193). Executables, DLLs and ROM databases are unchanged. Use `--server private.example` for a domain target or `--http-port 80` when serving the original port. Restore with `--restore /absolute/path/to/arena-backups/TIMESTAMP`.

Select **Host network** in the native access-point list. The emulator supplies the access point through its CommsDB/CommsDat integration.

Read an owned original ZIP or data.pak without extracting or modifying it:

```sh
.venv/bin/python -m arena.games.high_seize.content /absolute/path/to/High-Seize-v102.zip --verify --rules
```

This reader supports analysis; the live relay does not yet use its battlefield state. See [remaining work](todo.md).
