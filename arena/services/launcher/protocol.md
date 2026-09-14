# N-Gage Launcher protocol

### N-Gage 2.0 authentication

The Launcher on the 5320 posts `authenticateUser` to `/ngi/axis/services/NGICommunity` over HTTPS, with `gameClassId` 4444. Its response differs from the legacy Community endpoint: `authenticateUserReturn` contains `item` elements, with the first string `0` indicating success. Returning a numeric account ID directly produces the native invalid-credentials message even when the password is correct. `NAFAuthSrvr_V3`'s `CLoginXML` parser at linked address `0xb240` tracks the item index; its character handler at `0xb33e` compares item zero against the UTF-16 literal at `0xd440` and stores the authentication flag at object offset `0x74`.

The native Launcher accepted `["0", canonical_username]`, authenticated through legacy SNAP/XMPP, published presence and showed its green online indicator. These operations use the shared account store. The cookie also travels in the URL path, so request logging omits matrix parameters.

The Launcher is the N-Gage 2.0 entry point. Its service requests are routed to Community, profiles, messaging, rankings and achievements; this folder owns client configuration and integration requirements. Games must be started from the online Launcher on 5320 `rm-409`.

### Session recovery

Authenticated Community traffic renews a one-hour cookie session. The native ten-minute HTTP heartbeat is a public availability probe and does not renew identity. Public Rankings and Store pages also leave sessions unchanged. An expired cookie receives no private profile data; logging out and back in obtains a new authenticated cookie for the same shared account. The existing SNAP connection is a separate authenticated channel.

Application repository `20008bb7`, key `0x5`, contains the Launcher idle timeout in microseconds; the inspected package sets 1,320,000,000 (22 minutes). A running game may outlive this idle policy. Controlled-clock HTTP tests cover renewal, expiry and reauthentication independently of that UI timer.

SOAP profile exceptions and HTTP transport failures take different callbacks. In the inspected `nafuserprofile.dll`, the `CUserprofileServiceObserver` vtable at `0x105ac` points to `HandleMessageL` at `0xa376`, `HandleErrorL` at `0x9908` and `SetStatus` at `0x9916`. The error callback simply forwards the code to its observer; it does not request credentials itself. This matches the [MSenServiceConsumer contract](https://github.com/SymbianSource/oss.FCL.sf.mw.websrv/blob/master/websrv_pub/web_service_connection_api/inc/MSenServiceConsumer.h). A native HTTP 401 experiment did not cause reauthentication and is not implemented as a recovery mechanism.
