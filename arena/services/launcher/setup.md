# N-Gage Launcher setup

With EKA2L1 stopped, run from the project root:

```sh
.venv/bin/python -m arena.services.launcher.setup --data /absolute/path/to/Documents/data --game 2000afbc
```

The helper discovers NAF hostnames, updates emulator host mappings and sets the configurable HTTP endpoint to 8194. Repeat `--game` for additional UIDs; use `--server private.example` for a domain target. Every modified file is backed up. `--restore /absolute/path/to/arena-backups/TIMESTAMP` restores the originals. Game executables and ROM access-point databases are untouched.

NAF uses HTTPS for authentication even when other services use HTTP. Start the server with `--tls-port 8194 --tls-cert ... --tls-key ...`. Modern EKA2L1 takes over TLS by default: loopback/private LAN peers need no certificate installation; remote peers need a system-trusted certificate covering the mapped server hostname.

For old installations affected by the corrected Central Repository parser, `--reset-login rm-409` backs up and clears only that ROM's saved NAF login preferences. Use this recovery option only for damaged settings. It does not change accounts or saves.

For native Hooked writes on loopback, add `--local-native-http` to the runtime command. It requires an active SNAP login for the same name/address and trusts local processes. Remote writes still require session credentials. Public boards need no login.
