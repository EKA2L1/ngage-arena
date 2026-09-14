# Ashen validation

The unmodified multilingual 1.0.6 package completed native registration through HTTP 80, shared-account login through XMPP 5222, all nine statistic submissions, Send complete, and Game Total / Chapter 1 leaderboard retrieval. Wrong credentials were rejected; a subsequent valid login succeeded. A stopped-server attempt remained cancellable, and reconnection succeeded.

Executable SHA-256: `e4faf7c1e2304e1d5c64ed8249576bf1957e4d2fb87e6182d1613e26fbde4d6c`. Original `sc_lib.dll`: `d34062e62081cd955ec3af34ea171212b9b3e40ff32ff3f90d9d1d66de15e019`. Final fork source: `56c3a2afe`, Release iOS Simulator. No guest panic or access violation was found.

Local evidence: `data/verification/ashen-v106-2026-09-14/` and `data/verification/ashen-final-2026-09-14/`. The current automated score/authentication coverage is in `arena/games/ashen/tests/test_community.py` and `arena/services/community/tests/test_community.py` and `arena/services/accounts/tests/test_accounts.py`.

## Native screenshots

The unmodified 1.0.6 checks on 14 September 2026 produced these original captures. The leaderboard images show the registered account and its submitted zero-score baseline.

- [Registration successful](./screenshots/registration-success.jpg).
- [Game Total leaderboard](./screenshots/game-total-leaderboard.jpg), captured in the final Release check.
- [Chapter 1 leaderboard](./screenshots/chapter-1-leaderboard.jpg).
