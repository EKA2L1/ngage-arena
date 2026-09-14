# N-Gage Launcher remaining work

- Repeat the verified native web Rankings and Store flow on the original HTTP 80 endpoint when its local relay is available; see the catalogue module for further operations.
- Investigate HTTP reauthentication with saved credentials and the Launcher’s explicit reconnect paths after cookie expiry. A transport-level HTTP 401 alone did not trigger recovery. Manual logout/login in the same native process is verified; an active SNAP session alone does not renew the HTTP cookie.
- Repeat the input/background/login controls when the host integration changes.
