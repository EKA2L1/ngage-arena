# Local N-Gage Arena

A private service for the native Arena screens in **Tomb Raider**, **Ashen**, **High Seize**, and the **N-Gage 2.0 Launcher / Hooked On: Creatures of the Deep**. Accounts are shared across games. This is an independent project used with EKA2L1; ROMs, games and Nokia's original online content are not included. Some Arena features remain unfinished; each module records its protocol, validation and remaining work.

## Start

Python 3.10 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m arena.runtime
```

Run from this directory. The default address is `127.0.0.1`, with Community HTTP on **8192/8193/8194**, XMPP on **5222**, SNAP UDP on **9090**, and Tomb Raider AirPlay UDP on **41001**. `--host` selects another listening address; `--data` selects the persistent data directory (default `data/`). Back up that entire directory while the server is stopped.

N-Gage 2.0 authentication also needs HTTPS. For local development, generate a certificate and start the combined HTTP/HTTPS listener:

```sh
mkdir -p data/tls
openssl req -x509 -newkey rsa:2048 -nodes -keyout data/tls/server-key.pem \
  -out data/tls/server.pem -days 365 -subj /CN=localhost
.venv/bin/python -m arena.runtime --tls-port 8194 \
  --tls-cert data/tls/server.pem --tls-key data/tls/server-key.pem --local-native-http
```

Use an EKA2L1 build containing the [host integration follow-up (#712)](https://github.com/EKA2L1/EKA2L1/pull/712), which enables host TLS by default. Connected loopback/private LAN addresses need no CA installation. Remote deployments need a system-trusted certificate covering the configured server hostname. `--local-native-http` allows native score/achievement reports from loopback clients with a matching active SNAP login; it trusts local processes. Remote writes require session credentials. Leaderboard reads are public.

## Connect EKA2L1

Add host overrides in iOS **Settings → Host Overrides**, Android **Settings → Hosts**, or Qt **Settings → Hosts**. Map each hostname to `127.0.0.1` for the iOS Simulator, a reachable LAN IP for another device, or your private server's domain. Values contain no scheme or port. For an Android emulator, use the host's reachable address instead of guest loopback.

| Game / service | Hostnames |
| --- | --- |
| Tomb Raider | `discovery.cng.n-gage.com`, `arena.cng.n-gage.com` |
| Ashen | `arena.n-gage.com`, `im01.ashen.torus.sf.yav4.com` |
| High Seize | `arena.n-gage.com`, `im.hs.redlynx.sf.yav4.com`, `bs01.hs.redlynx.sf.yav4.com` |
| N-Gage Launcher | `new.arena.n-gage.com`, `imps.arena.n-gage.com`, `snap.dev.naftest.nokia.sf.yav4.com` |
| Hooked On | `snap.creatures.arena.n-gage.com`, `snap01.creatures.ngidev.sf.yav4.com` |

N-Gage 2.0 packages can contain additional names; the [Launcher helper](arena/services/launcher/setup.md) discovers installed configuration. `www.n-gage.com` is also used for legal pages, which this service does not reproduce. HTTP Host headers retain the original names, so reverse proxies must accept them. Ashen's original registration uses HTTP **80**; expose that port or forward it to a Community listener.

Use the original multilingual Ashen **1.0.6** package: it needs only host mappings. [Tomb Raider setup](arena/games/tomb_raider/setup.md) retains its required client repairs and billing provider. [High Seize setup](arena/games/high_seize/setup.md) changes its configurable HTTP port. Enter Hooked through the [N-Gage Launcher](arena/services/launcher/setup.md), then use Arena Update.

See [module architecture](docs/architecture.md) for development and each game's `protocol.md`, `validation.md` and `todo.md` for supported behavior and limits.
