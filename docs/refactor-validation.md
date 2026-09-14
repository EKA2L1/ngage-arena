# Module refactor validation — 15 September 2026

The complete suite runs from the repository root:

```sh
.venv/bin/python -m unittest discover -s arena -t . -v
```

All **174 tests passed** in 8.488 seconds after moving tests and fixtures into their owning service/game directories. The previous suite had 179 cases; the five removed cases covered the deleted Ashen setup helper and obsolete CA-copy configuration. Remaining assertions were retained. The migration also corrected a test-only SQLite connection that was committed but never closed. No ResourceWarning remains in the final run.

The normal `arena.runtime` started HTTP 8192/8193/8194, combined HTTP/HTTPS 8194, XMPP 5222, SNAP UDP 9090 and AirPlay UDP 41001 using the existing `data/native-validation` database. No wrapper or tracing patch was used. The renamed billing-provider asset was found through the composition root.

On the final Release EKA2L1 simulator executable (SHA-256 `69a0739e76e6f310d5571ada8b654f75dc50b838821b3e6cfcb14e53f94a1a0b`), the original 5320 N-Gage Launcher logged in as account 1 after both `host-tls` and `tls-ca-file` were removed from emulator configuration. It displayed the green online indicator. Enter Text appeared for the focused native editor in the host's upper-right corner, accepted the password, and disappeared on return to Home. The login background remained complete.

Hooked was entered through that online Launcher, loaded its existing ACE save and completed Arena Update. The refactored server committed three total-stat reports for account 1, then the native ranking page returned with the existing 321 XP personal best and the second account's zero score. This is an upload/confirmation/read control on the existing authorized synthetic save; it does not revalidate natural fishing or every pending multiplayer feature.

The same EKA2L1 code passed the default Release simulator regression (12/12), Angry Birds input suite (5/5), Qt build and all three Android ABI builds. Targeted TLS/access-point tests passed 15,876 assertions in 12 cases. Standalone platform-trust probes accepted a valid public certificate, rejected an untrusted public certificate and mismatched hostname, and accepted a self-signed loopback peer with a mismatched name. Apple trust evaluation disables network fetching. Windows and Android native trust still rely on their platform build/runtime coverage; these Apple probes do not claim equivalent native UI runs there.

Local logs, screenshots and hashes are under `data/verification/followups-2026-09-15/`. Earlier native evidence and remaining gaps remain in each module's validation and todo files; the refactor does not promote unverified features to completed ones.
