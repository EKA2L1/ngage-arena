## Connect EKA2L1

Stop the emulator before preparing its data directory. A legally obtained N-Gage ROM and an installed copy of Tomb Raider are required; neither is included here.

```sh
.venv/bin/python -m arena.games.tomb_raider.setup --data /absolute/path/to/Documents/data
```

The helper:

- Adds exact DNS overrides for `discovery.cng.n-gage.com` and `arena.cng.n-gage.com`.
- Restores the disabled Arena entry point in the recognized game revision and repairs its sent-message cache initialization.
- Installs the locally built billing-provider replacement and writes the game's identification file.
- Saves every changed file in `data/arena-backups/<timestamp>/`.

It validates the complete decompressed game executable with SHA-256 before applying either client repair. Unknown revisions are rejected. Game executables are modified only in the user's installation and are not distributed by this project.

The multilingual retail 1.0 launcher already exposes Arena; it only needs the same sent-message cache repair. Its import and protection data are preserved. Some archives also contain a duplicate `system/apps/tr` icon pointing at a truncated, 512-byte `tr.app`. If that duplicate is selected instead of `tombraider.app`, move the duplicate directory outside the guest installation before launching.

The billing replacement does not edit CommsDB. On an N-Gage ROM without an access point, use an emulator build that provides **Host network** through the native CommsDB API. Older setup backups containing a communications database can still be restored.



## Tomb Raider content and local rules

The original Nokia service and its official downloadable content are not reproduced. A new database starts with directories and a welcome message. Import your own valid recordings and authored courses:

```sh
.venv/bin/python -m arena.games.tomb_raider.admin import-clip recording.i3d --name 'My recording'
.venv/bin/python -m arena.games.tomb_raider.admin import-guide recording.i3d --name 'Caves route' --level 1
.venv/bin/python -m arena.games.tomb_raider.admin import-course course.dat --name 'Caves course'
.venv/bin/python -m arena.games.tomb_raider.admin status
.venv/bin/python -m arena.games.tomb_raider.admin export 12003 exported.i3d
```

Director's Cut files contain a compressed game snapshot, input streams, and optional camera streams. Race files contain a course description, checksummed time, random seeds, and input streams. They are different formats and are validated separately. `author-course --help` describes how to create a course using an owned recording. Verify its generated time in the native game before importing it. Level 0 (Lara's Home) cannot be used as a race course because it lacks the crystal object required by the game.

Players can also publish a guide directly from Director's Cut: choose **Upload → Strategy guide → level**, then enter a caption. That recording appears under the corresponding level in **Strategy Guide**. The **Player clips** upload category continues to publish to the general clip directory.

Director's Cut selects a section of the game's existing recording buffer. Press **#** during play, select a point before the end, activate **Record**, then activate **Stop** at the desired endpoint. In the tested controls, Left/Right selects a toolbar icon and Up activates it; numeric **5** confirms the Camera/Upload/Preview submenu. Select the first toolbar icon to jump to the start of the available recording before setting the start marker. Shadow Racing also uses the game's latched forward movement: pressing Down stops Lara's run.

The game can show its **STRATEGY** icon inside a level and open a guide directory with the left softkey. After publishing a Caves guide, install the authored example below while EKA2L1 is stopped:

```sh
.venv/bin/python -m arena.games.tomb_raider.admin author-guide-links examples/caves-guide-links.json data/caves-guide-links.dat
.venv/bin/python -m arena.games.tomb_raider.setup --data /absolute/path/to/Documents/data --guide-links data/caves-guide-links.dat
```

The JSON array describes level, room, inclusive `[xmin, zmin, xmax, zmax]` tile bounds relative to that room, and the destination directory. The example links Caves room 0 to its guide directory. The helper validates native limits and backs up any existing `adverts.dat`; restoring that setup backup reverses the installation. This is an authored local map, not Nokia's original guide data.

Practice races do not award points. A downloaded challenge against another player awards **+10 for a win and -5 for a loss**, once per challenge. These are this server's rules, not a claim to reproduce Nokia's unpublished formula. A losing client may return its downloaded opponent recording; that file is retained for the outcome but never credited as the loser's personal best. Duplicate final submissions are idempotent. Monthly gold, silver, and bronze awards are computed from positive point totals in completed UTC calendar months.

The required billing provider source and S60 SDK build are in `guest/`; its checked-in output is `assets/abtesrv.dll`. Run its `build.cmd` from an S60 2nd FP3 SDK environment. The provider implements the original interface without sending SMS. These Tomb Raider repairs are still required; Ashen has no setup or binary patch.
