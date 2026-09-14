# N-Gage Launcher protocol

### N-Gage 2.0 authentication

The Launcher on the 5320 posts `authenticateUser` to `/ngi/axis/services/NGICommunity` over HTTPS, with `gameClassId` 4444. Its response differs from the legacy Community endpoint: `authenticateUserReturn` contains `item` elements, with the first string `0` indicating success. Returning a numeric account ID directly produces the native invalid-credentials message even when the password is correct. `NAFAuthSrvr_V3`'s `CLoginXML` parser at linked address `0xb240` tracks the item index; its character handler at `0xb33e` compares item zero against the UTF-16 literal at `0xd440` and stores the authentication flag at object offset `0x74`.

The native Launcher accepted `["0", canonical_username]`, authenticated through legacy SNAP/XMPP, published presence and showed its green online indicator. These operations use the shared account store. The cookie also travels in the URL path, so request logging omits matrix parameters.

The Launcher is the N-Gage 2.0 entry point. Its service requests are routed to Community, profiles, messaging, rankings and achievements; this folder owns client configuration and integration requirements. Games must be started from the online Launcher on 5320 `rm-409`.
