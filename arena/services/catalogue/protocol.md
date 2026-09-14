# Launcher Store protocol

On the 5320 Launcher 1.40.1557, **Store → Update Now** downloads four resources from the origin configured by application repository `20008bbb`. The observed path stem is:

```
/sh/output/frontpage_mcc-_mnc-_device-Nokia%205320d-1_lg-1_shid-0_ngi-1.40.1557_fw-04.13_hw-RM-409_cmcc-_cmnc-
```

The sequence is `frontpage*.xhtml`, `frontpage*.swf`, `featuredGame*.png`, then `featuredGame*.txt`. The same device/language suffix is applied to each name. These are public HTTP GET requests, independent of NAF's HTTPS authentication port. The installed defaults use `showroom.n-gage.com:80`.

The private service supplies original XHTML listing registered N-Gage 2.0 adapters (`app_uid` and `title`), with absolute links into the shared public point boards. The origin (including a configured port) comes from the validated HTTP Host header because the Launcher opens the downloaded document from a local file; relative links otherwise resolve to the guest C: drive. A valid static SWF companion satisfies the downloader's separate movie resource; the XHTML does not embed it. The icon is an original 56 × 56 PNG with its SVG source beside it. No original Nokia online assets are distributed.

Featured metadata is a BOM-prefixed UTF-16 document with four newline-terminated fields: title, description, `dd/mm/yyyy`, and numeric catalogue item ID. The service uses the first listed game's class as its own catalogue item ID; this is not a claim about Nokia's original product IDs. Display text comes from the game adapter, and the date is the current catalogue publication date.

GET and HEAD return bounded content with explicit length/type and no session creation or renewal. Unsupported resource names and write methods are rejected. Client model/firmware suffixes are not reflected into HTML or used as filesystem paths. Downloads, purchases, licences and original promotional content are not provided.
