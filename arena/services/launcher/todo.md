# N-Gage Launcher remaining work

The current login, session-recovery, web Rankings and Store frontend checks are complete. Further catalogue operations are tracked in [catalogue](../catalogue/todo.md).

Saved-credential recovery is verified through explicit logout/login, normal Launcher exit/reopen and server restart; see [setup](setup.md) and [validation](validation.md). Automatic HTTP recovery is not observed with either saved or unsaved credentials. Future host integration changes should repeat the input/background/login controls recorded in validation.
