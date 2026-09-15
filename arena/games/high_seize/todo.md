# High Seize remaining work

- Connect owned map/unit resources and combat calculations to authoritative battlefield state: terrain, loaded units, fog, scripts and commander abilities.
- Implement and verify ordinary victory conditions, ranked settlement and remaining room filters. Surrender is the verified ending.
- Investigate intermittent elapsed-time differences: match 3 reported 10:59 versus 11:00; match 4 agreed at 3:24. EndGame has no time field, so trace native accumulation, freezing and rounding before choosing a fix.
- Complete unimplemented community/game operations without inventing successful responses.
- Diagnose partial redraw artifacts in native High Seize forms and result labels at the emulator layer; screenshots preserve the observed artifacts.
- Resume the paused authoritative battlefield work from the named EKA2L1 task checkpoint. The standalone loader currently initializes all 66 owned maps, MPS1 units, cargo, ownership, HP, ammunition and rations, with 202 service tests passing, but it is not yet connected to room lifecycle, actions or victory. Its implementation is kept in the `high-seize-authoritative-battlefield` git stash.
- Resume the emulator redraw investigation from the `high-seize-no-redraw-storing-background` stash in the sibling EKA2L1 repository. Local input-field redraws keep the complete High Seize login background and passed Release regression 12/12 plus 267 core tests; popup removal still needs a visible-region regression check before the fix can be committed.

## Host-only retail validation follow-up — 15 September 2026

- Complete the untouched retail `arena.amr` login response after Community `checkImei`. EKA2L1 revision `8e839439f` now delivers the request to local port 8193 without a libuv failure or guest crash, but the client rejects the current service response with its Server error page.
- Keep `game.id` out of all setup flows. It is a game-card-global retail file: the previous Tomb Raider setup overwrote it and made High Seize report `Invalid game card`.
