# N-Gage Launcher validation

Launcher completed HTTPS login, online indication, game history, editable profile round trips, shared points, friend acceptance, bidirectional chat and offline-message retrieval. The Hooked game was started from Launcher and completed positive score uploads. Native removal, rejection, reinvitation and acceptance now refresh both online clients without restart. Detailed evidence is in the owning service/game validation files.

On 15 September 2026, both original Launchers completed logout and login again without restarting EKA2L1. This required the shared emulator to dispatch the rm-409 `RSocket::CancelAll` opcode `0x24`: the missing handler left NAFIMPS blocked in a synchronous call and froze the Launcher during logout. Existing cancellation logic is reused, without modifying the guest DLLs. The final Release executable SHA-256 is `571d45cccc1032f4a19af90d5e76e28548fa3e9f2440b395722230d48456caf4`. Default simulator regression passed 12/12, screenshots were reviewed, and the complete core run passed 260 cases / 27,300 assertions. The affected native sessions had no guest panic, access violation or unhandled opcode 36 after the fix.

Initial Store checks rendered cached catalogue content; live download validation is recorded below. Login with friends sends `proximitylist` requests for `ngpsglobal` and per-game `ngps`, with `above=below=0`; the Points pages request nearby friend comparisons with `above=below=2`. Both include a comma-separated `userList` ending in a comma and space. These queries are now supported; native evidence is recorded under [rankings](../rankings/validation.md).

Historical EKA2L1 validation, including IME, background repaint, hostname overrides and temporary access points, is in [emulator validation](../../../docs/emulator-validation.md).

## Live invitation and friend refresh — 15 September 2026

Fork `0acda1674` and the equivalent upstream patch use Release executable SHA-256 `98267edef3f7c6aa2b0aec834a984afe928866a19abd619635a45719c50ef9f0`. Both original 5320 Launchers were freshly started with this build and the ordinary private server, without debugger intervention. Accepting a pending request immediately added the recipient to the running sender's Friends page. Online removal displayed its native notification. The sender then submitted `Release live after removal`; the running recipient displayed that exact new invitation and downloaded/converted a fresh avatar file. It chose Decline, which cleared the pending request and relationship. A further native `Release live after decline` invitation immediately appeared. Accept restored both directed grants, cleared all pending requests, and both Friends pages displayed the peer with consistent 30 / 10 N-Gage Points and avatars. No guest database or friendship row was edited during final validation.

The fix combines a nonempty downloadable default avatar in profiles with EKA2L1's AppArc `AppForDataType` implementation. Protocol diagnosis and ownership are documented under [profiles](../profiles/protocol.md). Temporary full-roster injection did not fix live invitations and is absent from the implementation. Default simulator regression passed **12/12** with screenshots reviewed; the complete core run passed **263 cases / 27,314 assertions**, and private service tests passed **178/178**. Final native logs contained no guest panic, access violation, graphics halt or unimplemented AppArc opcode 14. Evidence is in `data/verification/launcher-live-2026-09-15/`. Earlier input/TLS/platform coverage remains applicable to those unchanged paths; platform CI covers the new shared AppArc code.

## Embedded HTTP connection sharing — 15 September 2026

At the earlier connection-sharing stage, fork `778bba529` and equivalent upstream `0b2628261` completed named `RConnection` cloning, which the web Rankings view uses for embedded HTTP. Release executable SHA-256 is `14126694d4caad249577d1705b435944d386dca7c479a1ca4f27bb017f28611e`. The native page could then exit Downloading Files and return to Points; live web content was not yet verified at that revision. No guest patch or debugger completion was used. Default regression passed **12/12**, Angry Birds passed **5/5**, and both screenshot sets were reviewed. The complete core run passed **267 cases / 27,342 assertions**. Private service tests passed **182/182**. Evidence is in `data/verification/launcher-points-2026-09-15/` and `/tmp/eka2l1-regression-launcher-clone{,-angrybirds}/`.


## Live web and session follow-up, 2026-09-15

Fork `40e065399` and equivalent upstream `28865b38e` use Release executable `e1fcb231bf68fbce3cc3c83a0b0e2ea05ced50ba0a186e3c071240d63c309c9b`, which includes the pre-reform RConnection Control packet layout and the PSVariables GPRS/WCDMA properties. Read-only native breakpoints confirmed successful Control and named-open results. The remaining browser leave came from `HttpFilterConnHandlerObserver::SetBearerTypeAndUid`, which read missing system property `0x101f75b6 / 0x100052db`; publishing the GSM-attached state let the browser issue its real HTTP request.

The original 5320 Launcher then displayed the live Hooked web Rankings page with `adgjmptw` 30 and `wtpmjgda` 10, highlighting the signed-in player. This used normal Release execution without guest code changes or debugger request completion. The local HTTP 80 relay was unavailable, so the application repository URL was temporarily configured to port 8192 with a backup. Original-port validation remains dependent on restoring that relay.

On a second native Launcher (same Release, process 32664), an injected Community clock advanced 3,601 seconds while the guest clock and code remained unchanged. The next private profile request expired the cookie and returned no authenticated user. The existing SNAP session stayed online; no automatic HTTP reauthentication was observed. Manual logout/login in the same guest process obtained a new authenticated session, restored profile requests to account 2 and retained the accepted friend and 30-point comparison. The diagnostic clock wrapper is kept only in ignored validation data; the normal runtime was restored afterward.

The complete core run passed 267 cases / 27,346 assertions. Default Release regression passed 12/12, including Final Battle, Calculator and N95 Calculator; screenshots were reviewed. Angry Birds passed 5/5 on the same Release binary in the peer simulator, including visual menu/carousel checks. The primary CoreSimulator runtime had stalled screenshot requests and recovered after restart; no simulator data was erased. Full private-service tests passed 193 cases, including public pages and expiry/reauthentication over real loopback HTTP.

The same final Release Launcher completed Store → Update Now and rendered the private catalogue after downloading all four resources. Activating its absolute ranking link made a real public HTTP request and displayed the shared 30 / 10 totals while the Launcher was offline. See [catalogue validation](../catalogue/validation.md).

All four backed-up application repository text/persistence files were restored byte-for-byte after native validation. Emulator host mappings and the ordinary private server remain configured.

A further controlled expiry trial on the same final Release (native process 44267) changed only the first expired profile response from HTTP 200 to HTTP 401. The request arrived with its cookie after a 3,601-second server-clock advance. The Launcher stayed SNAP-online on its cached Friends screen and sent no new authentication request during the observation window. The password-save checkbox was disabled, so this does not establish behavior with saved credentials. This diagnostic response override was removed afterward; it is not part of the service. Evidence is in `data/verification/launcher-expiry-2026-09-15/`.

## Saved credentials and reconnect, 2026-09-15

The same final Release executable was tested with **Save password on device** selected in the original login page. Native host process 61534 authenticated account 2 at 06:16:50 (runtime log time). Advancing only the injected service clock by 3,601 seconds expired its next `getFriendsMiniProfiles` request at 06:17:22. The normal SOAP response denied private data. No new authentication request appeared during the following 77 seconds before manual logout; SNAP stayed online and the native UI retained its cached friend and point totals.

Selecting Logged Out and then Available to Play issued fresh HTTPS authentication at 06:18:56 without a password prompt. Profile requests again resolved to account 2. Exiting the Launcher normally and reopening it in the same host process initially showed offline; selecting Available to Play authenticated using the saved password at 06:20:36. Restoring the ordinary server closed SNAP and made the native indicator offline. A further explicit reconnect authenticated at 06:21:37 without asking for credentials. The accepted friend and shared point totals remained present.

This trial used no guest code, account, friendship or credential-file edits. The clock wrapper was removed from the running service afterward. Screenshots and the redacted request trace are in `data/verification/launcher-saved-expiry-2026-09-15/`. The native log had no guest panic, access violation or graphics halt; existing OOM-server stub warnings remain. The unchanged implementation reuses the complete 193-test service run and the Release regression results above. [CI on upstream `28865b38e`](https://github.com/EKA2L1/EKA2L1/actions/runs/34899623233) passed iOS, Android, Windows, Linux, macOS, sanitizers and dyncom differential tests.

## Original HTTP 80 endpoints, 2026-09-15

With the local HTTP 80 relay restored, the original Launcher completed the same flow on Release SHA-256 `e1fcb231bf68fbce3cc3c83a0b0e2ea05ced50ba0a186e3c071240d63c309c9b` (native host process 73244). Both repository text files and both persisted repositories matched their original backups before and after the run. Rankings used `http://playapps.ngage.mobi/rankings.html`; Store used the original `http://showroom.n-gage.com/sh/output/` resources. No application URL or guest binary was changed.

While offline, Store → Update Now downloaded all four resources, displayed the private catalogue, and opened its public ranking link with the shared 30 / 10 point totals. After normal HTTPS login, My Profile → Hooked → Rankings made another live GET and displayed the same totals with the current player highlighted. The native log had no guest panic, access violation, graphics halt or unhandled opcode. This closes the earlier temporary-port validation gap. Screenshots, repository hashes and the bounded server log are in `data/verification/launcher-http80-2026-09-15/`.

## Key screenshots

| Native result, 15 September 2026 | Screenshot |
| --- | --- |
| Explicit reconnect after reopening Launcher, using its saved password; green online indicator | [Reconnected home](screenshots/2026-09-15-saved-password-reconnect.jpg) |
| Accepted friend and 30 shared points retained after ordinary-server reconnect | [Friends](screenshots/2026-09-15-friends-after-reconnect.jpg) |
| Live signed-in Hooked web rankings on the original HTTP 80 URL; current player highlighted, 30 / 10 points | [Rankings](screenshots/2026-09-15-signed-in-hooked-ranking.jpg) |

These unedited screenshots show the native result states. The server trace and repository hashes described above establish the reconnect requests and unchanged original URLs. Store download and offline public ranking screenshots belong to [catalogue validation](../catalogue/validation.md#key-screenshots).
