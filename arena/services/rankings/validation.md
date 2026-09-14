# Rankings and points validation

Native Hooked uploaded and retrieved all five positive score categories using edited saves, with a second account independently reading the boards. Launcher and friend cards displayed the same 30 earned points as anonymous boards. See the Hooked and messaging validation files. `arena/games/hooked/tests/test_rankings.py` and `arena/services/rankings/tests/test_http.py` and `arena/services/rankings/tests/test_points.py` cover authorization, account separation, filter scope, retry/reopen and point consistency.
