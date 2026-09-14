# High Seize remaining work

- Connect owned map/unit resources and combat calculations to authoritative battlefield state: terrain, loaded units, fog, scripts and commander abilities.
- Implement and verify ordinary victory conditions, ranked settlement and remaining room filters. Surrender is the verified ending.
- Investigate intermittent elapsed-time differences: match 3 reported 10:59 versus 11:00; match 4 agreed at 3:24. EndGame has no time field, so trace native accumulation, freezing and rounding before choosing a fix.
- Complete unimplemented community/game operations without inventing successful responses.
- Diagnose partial redraw artifacts in native High Seize forms and result labels at the emulator layer; screenshots preserve the observed artifacts.
