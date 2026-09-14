# Ashen protocol

## Ashen Community and SNAP

Ashen uses Community SOAP at `/n-gage/axis/services/Community`, then legacy XMPP on TCP 5222. `createUser` returns `createUserResponse`; `authenticateUser` returns the numeric local account ID. The SDK asks for `jabber:iq:auth`, sends the lowercase SHA-1 of the password in the XMPP password field, retrieves its roster and publishes presence. The server authenticates that credential against a salted scrypt verifier. It derives the submitting account from the authenticated stream, not the caller's `snap_name` attribute.

Game class 42318 sends `segachat_send_event` to `reporter@ngage-auth`, event type `submit`. Its nine integer statistics are `level_1` through `level_8` and `game_total`. Personal bests only increase. Queries use `segachat_retrieve_req` to `retrieval@ngage-auth`, event type `topn`, with XML escaped inside `retrieve/request`. The native query selects `HIGHSCORES`, offset 0, limit 7, all-time period, natural ordering and CSV format. The response is `segachat_retrieve_resp`, with escaped text inside `retrieve/response`: status and message lines, a pipe-delimited query header, then `name|rank|score|0` rows. Empty boards return zero rows.

The original multilingual Ashen 1.0.6 executable and its bundled libraries work without binary modification. Its ArenaFoundation client waits for the legacy RGenericAgent stage EConnectionOpen (14). High Seize also waits for the subsequent EIfProgressLinkUp (1000), defined by the Symbian 6.1 interface progress range. These differ from modern RConnection KLinkLayerOpen (7000); the HLE connection must expose the legacy agent and interface stages in order. Configure the two host mappings listed in the root README. No setup helper or game binary patch is required.
