# Local N-Gage Arena

Local services for **Tomb Raider**, **Ashen**, and **High Seize**, with N-Gage 2.0 Launcher and **Hooked On: Creatures of the Deep** support under development. They use the games' native Arena screens and protocols. This project is independent of EKA2L1; the emulator needs working EKA1 networking and a configurable DNS override. High Seize has an experimental filtered-room service; its remaining limits are listed below.

The Tomb Raider service listens on UDP port **41001**. SQLite stores accounts, recordings, race results, challenge outcomes, messages, and monthly league points. Player identity is derived from the emulated device identity using a private HMAC key; raw device identifiers and passwords are not stored or logged.

## Start the server

Python 3.10 or newer is required. The installation helpers use PyYAML; High Seize authentication also uses PyCryptodome.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m arena.runtime
```

Run commands from this directory. The default bind address is `127.0.0.1`; the default database directory is `data/`. Back up the entire data directory while the service is stopped, including `community.sqlite3`, `arena.sqlite3`, and `identity.key`. Use `--host 0.0.0.0` only when intentionally serving other devices on a trusted local network.

## Shared accounts and game modules

`arena.runtime` starts Community HTTP (8192, 8193, 8194), XMPP (5222), SNAP UDP (9090), and Tomb Raider AirPlay UDP (41001). All listeners use the same `--data` directory. The older `arena.ashen` and `arena.server` entry points remain compatible, but must not run alongside the unified service on the same ports. Use `--airplay-port 0` to disable AirPlay, or repeat `--http-port` to select HTTP listeners.

`arena.accounts.AccountStore` owns password authentication and device bindings in `community.sqlite3`. `arena.community.CommunityServer` implements SOAP sessions and XMPP; it delegates game requests through `arena.games.GameRegistry`. Ashen's score repository and High Seize's profile/battle adapter live under `arena.games`. A new game registers an adapter in `arena.runtime.default_games`; it must not create another password database. Game records reference the shared account ID. Tomb Raider retains its original local player IDs so recordings and challenge ownership remain stable, with `Store.account_id` resolving the shared identity.

Profiles, friend subscriptions, presence and offline messages are shared services. `arena.messaging` stores contacts against account IDs and presents JIDs using each client's game domain. An N-Gage 2.0 adapter declares `app_uid` as well as `game_class`; the registry maps the Launcher's UID-only game history to the same achievement totals used by point boards. Client-uploaded profile point fields cannot replace earned totals.

Stop existing services before upgrading. The first start takes a SQLite backup of an existing `ashen.sqlite3` into `community.sqlite3`, preserving account IDs, password verifiers, scores, and match records. The original database remains untouched and is no longer used by the service. Repeated starts do not import it again. Separate historical data directories are **not** merged by matching usernames.

Tomb Raider sends a device identifier, not a password. Its existing or newly created players receive a separate device identity even if a password account has the same name. The local service operator can explicitly bind a player to a shared account:

```sh
.venv/bin/python -m arena.accounts --data data create Player
.venv/bin/python -m arena.accounts --data data link-tomb 'Local player' --account Player
```

Both commands prompt for the account password. Binding requires access to the local service data and a valid password, preserves the Tomb Raider nickname and records, and refuses to transfer a device already linked to another account. Treat a linked emulator's device identity as an account credential. The same password account can authenticate through the legacy Community endpoint and `/ngi/axis/services/NGICommunity`.

## N-Gage 2.0 development

Use the **N-Gage Launcher** on the 5320 (`rm-409`) to enter games. Direct launching of the game UID skips the required launcher setup. With the emulator stopped, configure the installed launcher and Hooked On:

```sh
.venv/bin/python -m arena.ngage2_setup --data /absolute/path/to/Documents/data --game 2000afbc
```

The helper reads hostnames from the installed NAF configuration, adds EKA2L1 hosts entries, and sets NAF's configurable web-service port to 8194. It backs up every changed file; `--restore <backup>` restores them. Repeat `--game` for additional installed game UIDs. The game and launcher binaries are unchanged. This configures connectivity; it does not imply that all N-Gage 2.0 service operations are implemented.

NAF uses HTTPS for account authentication even when its general Community URL uses HTTP. Serve both on port 8194 with a certificate whose subject alternative names include the configured service names:

```sh
.venv/bin/python -m arena.runtime --tls-port 8194 --tls-cert /absolute/path/to/server.pem --tls-key /absolute/path/to/server-key.pem
.venv/bin/python -m arena.ngage2_setup --data /absolute/path/to/Documents/data --game 2000afbc --tls-ca /absolute/path/to/ca.pem
```

For native score and achievement uploads in this local simulator setup, add `--local-native-http` to the runtime command. This opt-in mode associates credential-free HTTP reports with an active SNAP login from the same loopback address. It trusts local processes, is disabled by default, and requires normal HTTP session credentials for remote writes. Public leaderboard reads do not require this option or a login.

The second command requires an EKA2L1 build with host TLS support. It enables `host-tls`, copies the public PEM trust bundle to `tls/arena-ca.pem` under the emulator's data directory, and sets `tls-ca-file` to that relative path. For a self-signed development server, pass its public certificate as the CA. The helper rejects private keys and backs up both configuration and any previous trust bundle. The host verifies the certificate chain and hostname while negotiating TLS 1.2 or newer. No guest certificate-store changes are needed. Keep the server private key outside version control.

The native Launcher has completed login over TLS 1.3, displayed its online indicator, uploaded game history, saved profile edits and downloaded server-side changes. Its original synchronization policy gives pending local edits precedence over server values until the local upload completes. Hooked On has entered its Costa Rica map from the online Launcher and completed its native Arena Update and leaderboard retrieval. A backed-up, locally edited test save verified all five score categories: 321 XP, 5.0 kg total weight, 3 items, a 2.5 kg Barracuda and 987 Costa Rica Classic points. These are synthetic test results, uploaded by the original game, not catches obtained through automated fishing. Repeated updates preserve personal bests and acknowledge individual journal events. Launcher also displays earned Arena achievements in its multiplayer points, matching the shared account database. Ranking reads are public; uploads require an authenticated account association. Native friend workflows and remaining Arena features still need validation; this is not a completed N-Gage 2.0 service. See [native validation](VALIDATION.md) for evidence and limits.

Older emulator builds can leave a damaged NAF Central Repository cache: an empty login setting contains permission text such as ` 0 sid_rd`, causing `KErrOverflow` before login. With a build containing the corrected repository text parser, add `--reset-login rm-409` once to back up and reset that ROM's local NAF login preferences. This clears saved local credentials and login preferences; server accounts and game saves are retained. The same backup restore command restores these preferences too.

On N-Gage 2.0 ROMs using CommsDat and lacking an access point, EKA2L1 provides a temporary **Host network** access point, including the WAP associations required by the launcher. Its records are supplied in memory and excluded from the persisted CommsDat repository. Existing guest access points are preserved. The setup helper does not modify the ROM or its access-point database.

## Connect EKA2L1

Stop the emulator before preparing its data directory. A legally obtained N-Gage ROM and an installed copy of Tomb Raider are required; neither is included here.

```sh
.venv/bin/python -m arena.setup --data /absolute/path/to/Documents/data
```

The helper:

- Adds exact DNS overrides for `discovery.cng.n-gage.com` and `arena.cng.n-gage.com`.
- Restores the disabled Arena entry point in the recognized game revision and repairs its sent-message cache initialization.
- Installs the locally built billing-provider replacement and writes the game's identification file.
- Saves every changed file in `data/arena-backups/<timestamp>/`.

It validates the complete decompressed game executable with SHA-256 before applying either client repair. Unknown revisions are rejected. Game executables are modified only in the user's installation and are not distributed by this project.

The multilingual retail 1.0 launcher already exposes Arena; it only needs the same sent-message cache repair. Its import and protection data are preserved. Some archives also contain a duplicate `system/apps/tr` icon pointing at a truncated, 512-byte `tr.app`. If that duplicate is selected instead of `tombraider.app`, move the duplicate directory outside the guest installation before launching.

The billing replacement does not edit CommsDB. On an N-Gage ROM without an access point, use an emulator build that provides **Host network** through the native CommsDB API. Older setup backups containing a communications database can still be restored.

EKA2L1's `config.yml` must support this general hosts mapping:

```yaml
hosts:
  discovery.cng.n-gage.com: 127.0.0.1
  arena.cng.n-gage.com: 127.0.0.1
```

Names are matched case-insensitively, with an optional final dot. Values may be IPv4 addresses, IPv6 addresses, or another hostname (without a URL scheme or port). A hostname target is resolved by the host operating system; mappings are applied once, so they do not form alias chains. Unlisted names continue through ordinary DNS. Edit these mappings in Settings → Host Overrides on iOS, Settings → Hosts on Android, or the Hosts tab of Qt Settings. All three editors use the same validation and preserve unrelated entries. With host TLS enabled, a hostname target also supplies the TLS server name and certificate identity; an IP target retains the original hostname. HTTP Host headers remain those sent by the guest, so a reverse proxy must also accept the original N-Gage service names. For an iOS simulator, localhost is the Mac's localhost. For a physical device, pass the Mac's reachable LAN IPv4 address with `--server` and bind the server to that interface.

The initial networking changes merged through [EKA2L1 upstream PR #707](https://github.com/EKA2L1/EKA2L1/pull/707); the additional Arena, host TLS, access-point and rendering fixes are in [PR #709](https://github.com/EKA2L1/EKA2L1/pull/709). The final tested fork source is `56c3a2afe`. An older emulator without these service fixes cannot connect just by adding the hosts entries.

Launch the N-Gage ROM (`nem-4`) and Tomb Raider, then choose **N-Gage Arena**. Choose a local nickname on first login. Changing the emulated device identity creates a separate local account; a nickname cannot be taken from another identity.

To undo installation changes, stop EKA2L1 and run:

```sh
.venv/bin/python -m arena.setup --restore /absolute/path/to/data/arena-backups/TIMESTAMP
```

## Ashen

Use the unified `arena.runtime` service described above. Ashen uses SNAP/XMPP on TCP **5222** for login, score submission and leaderboard retrieval. Its registration page uses Community SOAP on TCP **80**; expose that port through your deployment or reverse proxy to enable in-game registration. Keep `data/community.sqlite3` to preserve registered accounts and personal bests; the first run migrates an existing `data/ashen.sqlite3` without changing its contents. The database stores salted scrypt verifiers of the SDK login credential, rather than reusable passwords or raw device identifiers.

Stop EKA2L1 and prepare an installed copy of Ashen:

```sh
.venv/bin/python -m arena.ashen_setup --data /absolute/path/to/Documents/data
```

Use the original multilingual Ashen 1.0.6 package, including its accompanying libraries. This revision needs no game patch: the helper only updates `config.yml`, backs it up under `arena-backups`, and leaves all executable, DLL and ROM files untouched. Copies with disabled Arena imports should be replaced with the original package. Pass `--server private.example` to use a hostname instead of the default loopback address.

It preserves other DNS overrides and adds:

```yaml
hosts:
  arena.n-gage.com: 127.0.0.1
  im01.ashen.torus.sf.yav4.com: 127.0.0.1
```

Ashen additionally requires EKA2L1's Nifman progress, resolver hostname/address-length, and additional DLL search-path fixes. The hosts support merged in PR #707 alone is insufficient.

Launch Ashen (`0x101FD3E9`) on ROM `nem-4`, enter **N-Gage Arena**, and log in with an existing shared account (or register when the Community service is available on port 80). **Send High Scores** uploads personal bests for eight chapters and the game total; **World Rankings** retrieves the selected leaderboard. Empty leaderboards stay empty until players submit scores. The service keeps each player's highest submitted score, with deterministic ordering for ties. It does not run the game's physics or validate earned scores.

To restore the installation, stop EKA2L1 and use `arena.ashen_setup --restore /absolute/path/to/backup`. No game or SDK executable is distributed here. Native validation is tracked in [VALIDATION.md](VALIDATION.md).

## High Seize (experimental)

The service now handles native filtered rooms, commander/team setup, battle-message delivery, turn deadlines and surrender settlement. Two original 1.0.2 clients completed a two-player Blood Bay match, with matching winner, loser, turns and unit-loss counts. SQLite records the match, participants and ordered battle events, including server-generated Begin, End turn and End game. Repeated finish calls cannot replace an existing result.

Run the unified `arena.runtime` service described above. Stop EKA2L1 and configure the installed original multilingual 1.0.2 package:

```sh
.venv/bin/python -m arena.highseize_setup --data /absolute/path/to/Documents/data
```

This backs up and edits only the emulator's host mappings and the Arena framework's HTTP endpoint configuration. It defaults to Community port 8193; use `--http-port 80` for a deployment serving the original port, and `--server private.example` for a hostname target. The game executable and bundled DLLs remain unchanged. Restore with `arena.highseize_setup --restore /absolute/path/to/data/arena-backups/TIMESTAMP`.

On N-Gage ROMs with no IAP, the updated emulator uses the native CommsDB API to create a **Host network** access point and its legacy WAP associations. These are ordinary writable guest settings, created transactionally and retained across launches. Existing access points are preserved. No SDK database replacement is needed. Select **Host network** in the native Arena access-point list.

The final two-client check through `arena.runtime` verified movement, an attack leaving the same mortar at 47 HP on both displays, and automatic surrender settlement. Both result pages showed the same winner, 12 turns and 19:30 elapsed time. The service relays native actions; it does not implement the full game's simulation or authoritative CRC validation. General victory detection, ranked results, room-filter semantics and the remaining community features are unfinished. Earlier runs differed by one second in elapsed-time fields, so timing consistency is not established for every match. See [VALIDATION.md](VALIDATION.md) for the exact coverage.

The content reader inspects an owned original ZIP or `data.pak` without extracting or modifying game files:

```sh
.venv/bin/python -m arena.highseize_content /absolute/path/to/High-Seize-v102.zip --verify > data/highseize-content.json
```

It validates the resource catalogue and reports each map's encoded unit/property placements, including IDs, owners and coordinates. `--verify` also decompresses every other resource. This supplies input for developing the authoritative battlefield; it does not enable victory detection in the running service. Terrain codes and the remaining NDL sections are available through the Python reader. Script execution, loaded-unit expansion and combat rules are not implemented by this reader. No game assets are included in this repository.

## Tomb Raider content and local rules

The original Nokia service and its official downloadable content are not reproduced. A new database starts with directories and a welcome message. Import your own valid recordings and authored courses:

```sh
.venv/bin/python -m arena.admin import-clip recording.i3d --name 'My recording'
.venv/bin/python -m arena.admin import-guide recording.i3d --name 'Caves route' --level 1
.venv/bin/python -m arena.admin import-course course.dat --name 'Caves course'
.venv/bin/python -m arena.admin status
.venv/bin/python -m arena.admin export 12003 exported.i3d
```

Director's Cut files contain a compressed game snapshot, input streams, and optional camera streams. Race files contain a course description, checksummed time, random seeds, and input streams. They are different formats and are validated separately. `author-course --help` describes how to create a course using an owned recording. Verify its generated time in the native game before importing it. Level 0 (Lara's Home) cannot be used as a race course because it lacks the crystal object required by the game.

Players can also publish a guide directly from Director's Cut: choose **Upload → Strategy guide → level**, then enter a caption. That recording appears under the corresponding level in **Strategy Guide**. The **Player clips** upload category continues to publish to the general clip directory.

Director's Cut selects a section of the game's existing recording buffer. Press **#** during play, select a point before the end, activate **Record**, then activate **Stop** at the desired endpoint. In the tested controls, Left/Right selects a toolbar icon and Up activates it; numeric **5** confirms the Camera/Upload/Preview submenu. Select the first toolbar icon to jump to the start of the available recording before setting the start marker. Shadow Racing also uses the game's latched forward movement: pressing Down stops Lara's run.

The game can show its **STRATEGY** icon inside a level and open a guide directory with the left softkey. After publishing a Caves guide, install the authored example below while EKA2L1 is stopped:

```sh
.venv/bin/python -m arena.admin author-guide-links examples/caves-guide-links.json data/caves-guide-links.dat
.venv/bin/python -m arena.setup --data /absolute/path/to/Documents/data --guide-links data/caves-guide-links.dat
```

The JSON array describes level, room, inclusive `[xmin, zmin, xmax, zmax]` tile bounds relative to that room, and the destination directory. The example links Caves room 0 to its guide directory. The helper validates native limits and backs up any existing `adverts.dat`; restoring that setup backup reverses the installation. This is an authored local map, not Nokia's original guide data.

Practice races do not award points. A downloaded challenge against another player awards **+10 for a win and -5 for a loss**, once per challenge. These are this server's rules, not a claim to reproduce Nokia's unpublished formula. A losing client may return its downloaded opponent recording; that file is retained for the outcome but never credited as the loser's personal best. Duplicate final submissions are idempotent. Monthly gold, silver, and bronze awards are computed from positive point totals in completed UTC calendar months.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The tests cover packet layouts and paging, reordered and duplicate uploads, real UDP login/upload/download exchanges, challenge/result fields, identity ownership, race validation, scoring, messages, trophies, and reversible emulator setup.

`guest/` contains the source and S60 SDK build files for `assets/abtesrv.dll`. The DLL preserves the original provider interface while using the local server. It does not send SMS messages or require a cellular subscription.

See [PROTOCOL.md](PROTOCOL.md) for packet and replay layouts, native screen contracts, and unresolved historical features. [VALIDATION.md](VALIDATION.md) records the native simulator checks. Guide playback is verified; a separate live mentor character and native offline library for reopening downloaded guides after a restart are not yet restored.

After a guide has downloaded, its playback controls work locally even while the private server is stopped. Directory access and fresh downloads still require the service.
