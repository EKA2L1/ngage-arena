# Community HTTP and XMPP validation

Native legacy registration/login and Launcher HTTPS login were verified before this refactor. `arena/games/ashen/tests/test_community.py` and `arena/services/community/tests/test_community.py`, `test_profiles.py`, `test_tls.py` and ranking/achievement suites exercise live HTTP/XMPP framing, session policy, bad credentials and TLS listeners. The refactor changes locations and startup ownership; final results are recorded in [refactor validation](../../../docs/refactor-validation.md).
