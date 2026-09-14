# Catalogue validation

On 15 September 2026, the original 5320 Launcher 1.40.1557 completed **Store → Update Now** against the ordinary private service. It downloaded the device-specific XHTML, companion SWF, featured PNG and UTF-16 metadata in sequence. The page displayed the new Arena games heading and Hooked entry. Activating View Arena rankings issued a fresh public GET and displayed the shared account totals of 30 and 10. This worked while the Launcher was offline, without a Community cookie. No original client binary, score or account data was modified.

The cached XHTML needs absolute links: relative links resolved to the guest C: drive. Final validation downloaded the corrected content rather than substituting the local cached file. The service preserves the request origin, including its port, in those links.

EKA2L1 fork `40e065399` (upstream `28865b38e`), Release executable SHA-256 `e1fcb231bf68fbce3cc3c83a0b0e2ea05ced50ba0a186e3c071240d63c309c9b`, supplies the shared HTTP startup fixes. The original HTTP 80 relay was unavailable, so only the application repository URL port was temporarily set to 8192 using a reversible backup. The original repository text/persistence files were restored byte-for-byte afterward; original-port revalidation remains pending. Native evidence is in `data/verification/launcher-web-2026-09-15/`.

Six loopback HTTP tests cover registered game selection, escaped XHTML and working ranking links, request-origin preservation and invalid hosts, the SWF header/length, four-line UTF-16 featured metadata, the 56 × 56 PNG, HEAD, invalid resource paths and unsupported write methods. The full private-service suite passes 193 tests. No original client files are test fixtures.

## Original HTTP 80 download and link, 2026-09-15

The original 5320 Launcher, Release executable SHA-256 `e1fcb231bf68fbce3cc3c83a0b0e2ea05ced50ba0a186e3c071240d63c309c9b`, completed Store → Update Now using its unchanged `showroom.n-gage.com` URLs on HTTP 80. The local relay forwarded to the ordinary Community listener. The server recorded four new GETs for XHTML, SWF, PNG and featured metadata. The offline native Store rendered the private catalogue; its ranking link made a new GET and displayed the shared 30 / 10 point totals without logging in. A later signed-in Hooked Rankings view also passed on the original `playapps.ngage.mobi` address. All original repository files still matched their backups. Evidence is in `data/verification/launcher-http80-2026-09-15/`; this supersedes the earlier original-port limitation.

## Key screenshots

| Native result on original HTTP 80 URLs, 15 September 2026 | Screenshot |
| --- | --- |
| Store → Update Now rendered the private catalogue with its Hooked entry and ranking link | [Updated Store](screenshots/2026-09-15-original-http80-store.jpg) |
| Offline Store link opened public rankings with the shared 30 / 10 totals | [Public rankings](screenshots/2026-09-15-offline-public-ranking.jpg) |

The unedited screenshots preserve the final native pages. The four fresh resource requests and unchanged repository files are verified by the trace and hashes recorded above.
