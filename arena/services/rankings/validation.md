# Rankings and points validation

Native Hooked uploaded and retrieved all five positive score categories using edited saves, with a second account independently reading the boards. Launcher and friend cards displayed the same 30 earned points as anonymous boards. See the Hooked and messaging validation files. `arena/games/hooked/tests/test_rankings.py` and `arena/services/rankings/tests/test_http.py` and `arena/services/rankings/tests/test_points.py` cover authorization, account separation, filter scope, retry/reopen and point consistency.


## Native friend point queries — 15 September 2026

Both original 5320 Launchers logged in with an existing accepted friendship. The captured `ngpsglobal` and four installed-game `ngps` queries used a nonempty trailing-comma `userList` and zero-sized windows. Opening global and Hooked Points pages requested `above=below=2`. The peer's global page and both clients' Hooked pages displayed the two named comparison bars in descending point order, with the current player highlighted: adgjmptw 30, wtpmjgda 10. Solo points were 0 and multiplayer points matched the totals. Waiting for asynchronous synchronization is necessary; early frames show totals before the breakdown and friend bars arrive.

This is coverage of the native point-board consumer, beyond profile-derived friend cards. No scores, guest files or friendship rows were edited during this validation. The fixture `tests/fixtures/launcher-friend-points.xml` preserves the observed request shape with sanitized test names. Unit and HTTP tests cover a higher-scoring account outside the requested cohort, case-insensitive duplicates, unknown players, ties, per-game separation, malformed lists and public reads without creating sessions. The full private-service run passed **182 tests**. Evidence is in `data/verification/launcher-points-2026-09-15/`.

The separate web-based Rankings tab still has no live page content. Its connection-clone hang is an emulator issue, distinct from these completed point comparisons.
