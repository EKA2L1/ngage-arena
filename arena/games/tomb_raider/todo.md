# Tomb Raider remaining work

- Recover the separate mentor-character feature and a native offline guide library from evidence. Full recording playback is already supported.
- Original Nokia content and unpublished scoring remain unavailable; authored imports and the documented local +10/-5 policy are replacements.
- Repeat affected native flows after protocol changes, using both practice and two-account challenge controls.

## Retail cold-cache follow-up — 15 September 2026

- The untouched retail GSBAPP crashes in its own sent-message path if a new installation wins a challenge and submits a taunt before it has ever downloaded Messages: `A_storedmessages.dat` is absent and the client dereferences its null cache object. Opening Messages once downloads the server's Welcome message and initializes the cache. Re-test the full cold-cache sequence in that order and keep the retail executable unchanged; investigate whether the original command-10 event response can trigger the initial inbox download automatically.
