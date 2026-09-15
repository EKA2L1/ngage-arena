# N-Gage Arena

An independent N-Gage Arena private server for EKA2L1. It supports shared accounts across the original N-Gage and N-Gage 2.0 games; ROMs, games and Nokia content are not included.

| Game or service | Available features |
| --- | --- |
| Tomb Raider | Login, messages, recordings, races, challenges and strategy-guide clips |
| Ashen | Registration, login, statistics and leaderboards |
| High Seize | Login, rooms, two-player battles and results |
| Hooked On: Creatures of the Deep | Launcher login, score upload, leaderboards and achievement points |
| N-Gage Launcher | Profiles, friends, messaging, points, web rankings and Store catalogue |

Each module contains `protocol.md`, `validation.md` and `todo.md` with its exact coverage and remaining work.

## Start locally

Python 3.10 or newer is required:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m arena.runtime
```

The defaults are Community HTTP 8192/8193/8194 TCP, XMPP 5222 TCP, SNAP 9090 UDP and Tomb Raider AirPlay 41001 UDP. Use `--host` to listen beyond loopback and `--data` to select the persistent directory.

## Connect EKA2L1

In EKA2L1's **Hosts** settings, add these two mappings for the hosted service:

| Guest hostname | Target |
| --- | --- |
| `*.n-gage.com` | `ngage.yeatse.com` |
| `*.yav4.com` | `ngage.yeatse.com` |

Suffix mappings cover the original game, Store, login, XMPP and SNAP names. Host targets may include a port for local development, such as `arena.n-gage.com = 127.0.0.1:8192`. Remote HTTPS uses the target hostname for system certificate validation.

Install the original retail games and enter N-Gage 2.0 titles through the Launcher. No game, ROM, certificate or access-point setup helper is required. Tomb Raider downloads its billing provider from the server when needed.

See [the architecture](docs/architecture.md) for development details.
