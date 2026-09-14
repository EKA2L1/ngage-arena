# Service and game boundaries

`arena.runtime` is the composition root. It creates one `AccountStore`, registers game adapters, starts the HTTP/XMPP/SNAP/AirPlay listeners, and owns their shutdown. Run only this entry point for the combined service.

| Directory | Responsibility |
| --- | --- |
| `arena/services/accounts` | Password verifiers, account IDs, migration and explicit device binding |
| `arena/services/community` | HTTP/SOAP routing, sessions, XMPP connection lifecycle and TLS listener |
| `arena/services/profiles` | Profiles, game history and relationship records |
| `arena/services/messaging` | Roster grants, invitations, presence, online chat and offline delivery |
| `arena/services/rankings` | Ranking request validation, authorization and shared point boards |
| `arena/services/achievements` | Idempotent achievement journal and defined point values |
| `arena/services/snap` | Shared UDP framing, authentication, peer lifecycle and application callbacks |
| `arena/services/launcher` | N-Gage 2.0 configuration and Launcher integration requirements |
| `arena/services/catalogue` | Public Store pages and companion resources for registered N-Gage 2.0 games |
| `arena/games/tomb_raider` | AirPlay, replays, courses, challenges, billing provider and required setup |
| `arena/games/ashen` | Nine personal-best score boards and its XMPP adapter |
| `arena/games/high_seize` | Game packets, room/battle service, commander codec, owned content reader and combat rules |
| `arena/games/hooked` | Score categories, filtered boards, UID and achievement definitions |
| `arena/tools` | Shared setup target validation and backup restoration |

Each service and game owns `protocol.md`, `validation.md` and `todo.md`. Protocols describe recovered native contracts; validation distinguishes actual client evidence from synthetic tests; pending features stay explicit. Runtime files and validation captures remain under ignored `data/`.

## Adding a game

Create a directory under `arena/games` with those three documents and a game adapter. Register it in `arena.runtime.default_games`. Declare its recovered `game_class`; N-Gage 2.0 adapters also declare `app_uid` so Launcher history and achievement points join correctly. The registry rejects duplicate classes and UIDs.

Use the injected shared account store and reference canonical account IDs for game state. Implement only the adapter operations the client supports: XMPP reports/retrieval, ranking queries, or achievement definitions. Reject unsupported operations. Shared services own authentication, parsing, transaction confirmation and connection cleanup; game modules own title-specific payloads and rules.

A game with another wire protocol can receive its own listener from the composition root, as Tomb Raider does. The current SNAP UDP listener has one supplied High Seize application; another UDP game will need protocol-driven application selection or a separately configured listener. Avoid choosing a game by an arbitrary player-supplied username or creating a second credential database.

Tomb Raider keeps historical local IDs in `arena.sqlite3` for stable replay and challenge ownership and resolves them to shared IDs through explicit identity bindings. Ashen's old database migrates once to `community.sqlite3`; unrelated data directories are never merged by matching nicknames.

## Checks

```sh
.venv/bin/python -m unittest discover -s arena -t . -v
```

Tests and fixtures live in each service or game’s `tests/` directory and import the owning module directly. Shared protocol fixtures stay with their owning service. They cover real loopback HTTP/UDP/XMPP/TLS exchanges, persistence and recovered binary contracts. Native UI evidence is recorded by the owning module; passing protocol tests alone does not establish that an original game's UI completed a flow.

The removed `arena.ashen`, `arena.server` entry points are superseded by `arena.runtime`. The Ashen setup helper is obsolete. Remaining helpers are `arena.games.tomb_raider.setup`, `arena.games.high_seize.setup` and `arena.services.launcher.setup`; their purpose and restore commands are documented beside them. N-Gage 2.0 setup no longer configures host TLS switches or copies CA files.
