# Tomb Raider validation

## Tomb Raider baseline

The private service was exercised through the installed Tomb Raider game, GSB Arena UI and AirPlay client on N-Gage ROM `nem-4`, UID `0x101FBF9D`, in the iOS simulator. EKA2L1 used the final Release simulator build whose source matches fork commit `efb24fc9a` (base `167e5fd5252819fe4287cc3a91b55f3186f06c10` plus the general hosts and EKA1 networking changes). Debugger probes were detached and temporary emulator diagnostics removed before the final build and regression run.

| Path | Observed result |
| --- | --- |
| Cold login and persistent identity | The original Arena account reconnects after restarting the app and reinstalling the Release build. A second local device identity has a distinct account. |
| Director's Cut | A native Caves recording was trimmed, given a changed camera angle, previewed, captioned, uploaded, stored and downloaded for native playback. |
| Practice race | An authored Caves course was calibrated against the game's replay validation and completed with a visible wireframe opponent and finish crystal. Practice earns no league points. |
| Competitive challenge | A native 33.766-second recording was challenged by a 6.126-second run. The game displayed a win and +10 points. A loss displayed -5 points without crediting the returned opponent recording as the loser's best. |
| Taunt and revenge | A nonempty taunt was submitted before opening Messages in that cold client session. The opponent received it, selected the native Revenge action after a new login, downloaded the correct course, won in 2.490 seconds and submitted another taunt. The result displayed cumulative score 5 after -5 and +10. |
| Messages after identity restoration | Restoring the original account produced the incoming “A beat your time” message and the native Revenge action. |
| Monthly trophies | Temporary completed-month scores produced Gold: Arena and Silver: A in the native hierarchy. Those temporary events were removed after inspection. Live awards use actual completed UTC months. |
| Strategy guide | A locally recorded Caves clip was imported into the native level directory, downloaded and played with pause, rewind and fast-forward. A second recording was uploaded directly through the game's Strategy guide → Caves category with caption “Guide”, appeared in that level directory, and was downloaded into the native player. |
| Offline playback | With the local server stopped and no UDP listener on port 41001, the downloaded clip rewound from its end, returned to the start, played and paused at 4.12 seconds. This proves local playback within that loaded session; reopening saved guides after restarting offline is not yet verified. |
| Cold offline access | With port 41001 still closed, a restarted game retained the downloaded 642-byte `current.i3d`. Options offered no clip browser, and Arena entered Connecting before showing directories. The attempt was cancelled and the private service restored. No offline reopening path was found. |
| Guide entry inside a level | An authored Caves room-0 `adverts.dat` record displayed the native STRATEGY icon. The left softkey opened the level's guide directory directly and downloaded a clip into the native player. The same eight-byte record was then installed through the validated setup helper with a reversible backup. |

The separate live “mentor Lara” and native offline library for reopening downloaded guides after a restart described by historical accounts remain unverified and are not claimed as restored. Official downloadable courses and walkthroughs are not included. The imported clips and reference races in this local database are demonstration content, not a complete game walkthrough.

The multilingual retail 1.0 Arena retest on 14 September 2026 completed authentication, directory browsing, recording download/playback and a 701 ms practice result; reauthentication returned the persisted time. See [shared emulator validation](../../../docs/emulator-validation.md).
