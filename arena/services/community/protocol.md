# Community HTTP and XMPP protocol

### N-Gage 2.0 authentication

The Launcher on the 5320 posts `authenticateUser` to `/ngi/axis/services/NGICommunity` over HTTPS, with `gameClassId` 4444. Its response differs from the legacy Community endpoint: `authenticateUserReturn` contains `item` elements, with the first string `0` indicating success. Returning a numeric account ID directly produces the native invalid-credentials message even when the password is correct. `NAFAuthSrvr_V3`'s `CLoginXML` parser at linked address `0xb240` tracks the item index; its character handler at `0xb33e` compares item zero against the UTF-16 literal at `0xd440` and stores the authentication flag at object offset `0x74`.

The native Launcher accepted `["0", canonical_username]`, authenticated through legacy SNAP/XMPP, published presence and showed its green online indicator. These operations use the shared account store. The cookie also travels in the URL path, so request logging omits matrix parameters.

`CommunityServer` owns SOAP session cookies, HTTP endpoint routing and XMPP connections. It delegates profile, message, ranking and achievement operations to their services and game-specific XMPP reports to `GameRegistry`.

HTTP listeners support `Expect: 100-continue`; legacy registration/authentication uses `/n-gage/axis/services/Community`. N-Gage 2.0 uses `/ngi/axis/services/NGICommunity`. These return different native response envelopes. HTTP Host remains the original guest hostname even with a DNS override.

The TLS listener accepts HTTP and HTTPS on the same configured port. EKA2L1 handles modern TLS by default, directly trusts connected loopback/private LAN addresses and uses platform trust for remote peers. Remote certificates must cover the rewritten hostname. No emulator CA file is required. The server still needs a certificate and private key for HTTPS.

An anonymous GET availability probe receives a stateless empty 200. It neither creates nor refreshes authentication. Private profile operations require sessions. Ranking reads are public; score/achievement writes require credentials or the explicitly enabled loopback SNAP association. See the ranking and achievement protocols.
