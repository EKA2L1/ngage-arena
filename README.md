# Local N-Gage Arena

A local AirPlay server for the original N-Gage edition of **Tomb Raider**. It uses the game's native Arena screens and native replay files. It is independent of EKA2L1; the emulator only needs working EKA1 networking and a configurable DNS override.

The service listens on UDP port **41001**. SQLite stores accounts, recordings, race results, challenge outcomes, messages, and monthly league points. Player identity is derived from the emulated device identity using a private HMAC key; raw device identifiers and passwords are not stored or logged.

## Start the server

Python 3.10 or newer is required. PyYAML is used by the installation helper; the server itself uses the standard library.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m arena.server
```

Run commands from this directory. The default bind address is `127.0.0.1`; the default database directory is `data/`. Preserve both `data/arena.sqlite3` and `data/identity.key` when backing up the service. Use `--host 0.0.0.0` only when intentionally serving other devices on a trusted local network.

## Connect EKA2L1

Stop the emulator before preparing its data directory. A legally obtained N-Gage ROM and an installed copy of Tomb Raider are required; neither is included here.

```sh
.venv/bin/python -m arena.setup --data /absolute/path/to/Documents/data
```

The helper:

- Adds exact DNS overrides for `discovery.cng.n-gage.com` and `arena.cng.n-gage.com`.
- Restores the disabled Arena entry point in the recognized game revision and repairs its sent-message cache initialization.
- Installs the locally built billing-provider replacement and writes the game's identification file.
- Saves every changed file and the original communications database in `data/arena-backups/<timestamp>/`.

It validates the complete decompressed game executable with SHA-256 before applying either client repair. Unknown revisions are rejected. Game executables are modified only in the user's installation and are not distributed by this project.

EKA2L1's `config.yml` must support this general hosts mapping:

```yaml
hosts:
  discovery.cng.n-gage.com: 127.0.0.1
  arena.cng.n-gage.com: 127.0.0.1
```

Names are matched case-insensitively, with an optional final dot. Values are numeric IP addresses. Unlisted names continue through ordinary DNS. For an iOS simulator, localhost is the Mac's localhost. For a physical device, pass the Mac's reachable LAN IPv4 address with `--server` and bind the server to that interface.

The required emulator changes are tracked in [EKA2L1 upstream PR #707](https://github.com/EKA2L1/EKA2L1/pull/707). The tested fork source is `efb24fc9a`; an older emulator without its EKA1 service fixes cannot connect just by adding the hosts entries.

Launch the N-Gage ROM (`nem-4`) and Tomb Raider, then choose **N-Gage Arena**. Choose a local nickname on first login. Changing the emulated device identity creates a separate local account; a nickname cannot be taken from another identity.

To undo installation changes, stop EKA2L1 and run:

```sh
.venv/bin/python -m arena.setup --restore /absolute/path/to/data/arena-backups/TIMESTAMP
```

## Content and local rules

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
