# Tomb Raider AirPlay protocol

This document records the implemented subset of the original N-Gage client protocol. It is derived from the installed ARM binaries and native client exchanges. It is not a specification of the retired Nokia service. Names such as `DecryptAndDispatchMessageL` in the client do not imply encryption: this transport sends these fields directly over UDP.

## Transport

All integers are little-endian. Each UDP datagram starts with `u32 sequence, u8 command, u8 flag, u16 extra`. A packet with flag 0 requires command 250, flag 1, with the acknowledged sequence as a four-byte body. Sequences suppress duplicates. The server limits outstanding replies to four and retries with backoff. A short initial response delay allows the client's separate network and UI IPC requests to finish arming on localhost.

Strings are `u32 byte_length` followed by that many Latin-1 bytes. They are not null-terminated. The server does not log login strings. It stores an HMAC of the emulated device identity, with a private per-database key, to associate subsequent logins with the same local account.

| Request | Body | Reply |
| --- | --- | --- |
| 50 | `u16`, provider version string, MD5 string, two `u16`, identity string, string | 150: status byte and string; status 1 requests a provider update |
| 51 | empty | 121: provider DLL chunks |
| 0 | five `u16`, game string, `u32`, nickname, password, device identity, subscriber identity, `u8` | 120: login status and auxiliary byte |
| 2 | nickname, device identity | 120: login/rename status |
| 1 | disconnect | no application reply |
| 9 | `u32 parent`, filter string | 124: directory pages |
| 10 | empty | 125: an empty event page |
| 11 | filter string | 126: message pages |
| 3 | `u32 object_id`, token string | 121: content chunks |
| 6 | `u16 type`, `u32 size`, caption string, two `u32` values | 122: begin sending chunks |
| 7 | target string, `u32 size`, caption string, two `u32` values | 122: begin sending clip chunks |
| 8 | `u32 start`, inclusive end, chunk size, bytes | 123 after the complete validated upload is persisted |
| 12 | eight timestamp bytes | 127: the same eight bytes |

Type 1001 is a race upload; type 1002 is a Director's Cut upload. Downloadable Director's Cut objects use type 2222. The client writes them to `current.i3d` and returns command -2 to the game. Race objects use type 1001, `ghost_in.dat`, and command -3. The recognized client's type 2223 filename is the literal `NOT USED !`; the service does not publish that type.

Download chunks carry `u32 total_size, start, inclusive_end, chunk_size`, then bytes. Normal downloads append `u32 object_id`; the provider bootstrap does not. Upload chunks may arrive out of order. Exact duplicates are harmless; overlapping or inconsistent ranges are rejected. A download token beginning with `701,` identifies a competitive race challenge. Practice downloads do not award points.

## Native directories and messages

A directory page begins with three bytes: record count, zero-based page index, page count. Directory pages then carry `u32 parent`. Each object is `u32 id, u16 kind, u16 billing, u32 value1..value4`, followed by two strings. The client has small fixed buffers: object names are limited to 20 bytes and player names to 12.

The client chooses its renderer by parent ID, independently of the displayed directory name:

| Parent | Native role |
| --- | --- |
| 1 | Main menu |
| 900 | Course directory |
| 912 | High scores / league table |
| 915 | Two-row challenge page |
| 918 | Result and outcome rows |
| 1201, 1202–1211 | Upload category and caption selection |
| 1301 | Player clips, a generic directory |
| 1401, 1402–1501, 920 | Guide category / clip download selection |
| 501 | Messages |

Challenge row 0 describes the opponent. Row 1 describes the current player and carries the course and downloadable opponent object IDs. Both rank strings must contain decimal digits; an empty string asserts in the native client. Result row 0 carries the uploaded time, cumulative monthly score and rank. Row 1 supplies the won/lost flag and absolute point delta. Negative scores are transmitted in the original 32-bit representation.

The local upload catalogue uses parent 1202 for ordinary clips and 1203 for guides. Type-2 category leaves 3000–3015 name the guide levels. The client echoes the selected category ID in the upload's second `u32` value; the server routes those clips to parents 1402–1417. This was verified with a native Caves upload carrying values `1, 3001`, then downloaded from parent 1403.

A message contains its body string, two type bytes, message ID, sender string and two `u32` values. Type 1 displays the welcome message; type 0 displays a challenge message with the native Revenge action. That action requests directory 915 with `sender,revenge`. The server restores the corresponding course from the latest completed winning challenge against the recipient, so revenge works after a fresh login.

The client caches received and sent messages in a Symbian stream file. `logincookie.dat` is also a Symbian stream, not a plain C string: a native five-character nickname has a one-byte descriptor-length prefix followed by its five characters. The setup helper leaves account cookies and saved games alone.

## Replay containers

Director's Cut files start with four `u32` values: snapshot frame, first frame, last frame and compressed snapshot size. A zlib stream expands to a 12,684-byte game snapshot. The remaining input block contains a four-byte value followed by 17 streams, each with a `u16` byte length. Optional camera data begins with `u32 1234` and five similarly length-prefixed streams.

A race begins with the packed layout `<IHHHIIIiiiH`: course ID, level, room, checkpoint count, yaw, excluded item mask, frame limit, start X/Y/Z and marker 0x1234. It is followed by checkpoint XYZ triples, completion time in milliseconds, a transformed time checksum, replay frame bounds, random seeds and the 17 input streams. See `arena/replay.py` for the checksum and bounds checks. The native game replays the reference input and compares the generated finish time before starting the live race; merely supplying a plausible time is insufficient.

The server validates the file structure, time checksum and registered course description. It does not run Tomb Raider's physics and is not an anti-cheat service. A losing client may upload the downloaded opponent replay. That submission records a loss but must not become the loser's personal best. Completion is committed once per downloaded challenge; a repeated final file returns the original result.

## Scope and unresolved historical claims

The implemented guide path plays full native recordings with pause, rewind and fast-forward. It does not yet reproduce the separate, simultaneously controllable “mentor Lara” described in contemporary player accounts, or an independent offline text-tip viewer. Neither a valid mentor file format nor that text viewer has been established in the recognized binaries. These are not claimed as verified features.

The game also reads an optional `adverts.dat` table to offer location-specific guide entry points. Its eight-byte records combine room, tile bounds and level in a packed word, followed by a directory ID. The installed game has no such file. The setup helper does not invent an official table or patch the game into a new guide mode.

Official courses, walkthrough recordings, original accounts and Nokia's unpublished scoring formula are unavailable. Local imports and the documented +10/-5 policy are explicit replacements. No ROM, game executable, extracted snapshot or recording is included in source control.
