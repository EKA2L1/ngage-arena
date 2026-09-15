# High Seize remaining work

- Connect owned map/unit resources and combat calculations to authoritative battlefield state: terrain, loaded units, fog, scripts and commander abilities.
- Implement and verify ordinary victory conditions, ranked settlement and remaining room filters. Surrender is the verified ending.
- Investigate intermittent elapsed-time differences: match 3 reported 10:59 versus 11:00; match 4 agreed at 3:24. EndGame has no time field, so trace native accumulation, freezing and rounding before choosing a fix.
- Complete unimplemented community/game operations without inventing successful responses.
- Diagnose partial redraw artifacts in native High Seize forms and result labels at the emulator layer; screenshots preserve the observed artifacts.
- Resume the paused authoritative battlefield work from the named EKA2L1 task checkpoint. The standalone loader currently initializes all 66 owned maps, MPS1 units, cargo, ownership, HP, ammunition and rations, with 202 service tests passing, but it is not yet connected to room lifecycle, actions or victory. Its implementation is kept in the `high-seize-authoritative-battlefield` git stash.
- Resume the emulator redraw investigation from the `high-seize-no-redraw-storing-background` stash in the sibling EKA2L1 repository. Local input-field redraws keep the complete High Seize login background and passed Release regression 12/12 plus 267 core tests; popup removal still needs a visible-region regression check before the fix can be committed.

## Host-only retail validation follow-up — 15 September 2026

- Re-test the untouched retail `system/libs/framework/arena.amr` (SHA-256 `7da8bbcfcad05fadb87843d398f811a5a19963c077699e84670a1429a08a80c2`) with `arena.n-gage.com = 127.0.0.1:8193`. The game launches after restoring the retail `game.id`, but entering N-Gage Arena currently ends at the native server-error page; EKA2L1 logs a libuv `ECONNREFUSED`. Determine the actual translated destination before claiming the port-mapping path passes.
- Keep `game.id` out of all setup flows. It is a game-card-global retail file: the previous Tomb Raider setup overwrote it and made High Seize report `Invalid game card`.
