# Resilient Image Delivery

Research for [Choose a resilient image delivery strategy](https://github.com/kriss-spy/daily-miku-base/issues/6), conducted 2026-07-17.

## Decision

Use a Raindrop-authoritative, mirror-first model. Raindrop continues to identify the selected bookmark and retain source attribution. Images that Daily Miku is authorized to reproduce are validated once, normalized, stored under a content-addressed key in public Vercel Blob, and referenced by the Raindrop `cover`. `https://dailymiku.dev/image/<date>` returns a short-cache `307 Temporary Redirect` to that controlled object.

Do not promise reliability through raw Pixiv/X hotlinks, forged request headers, page scraping, or an unrestricted live proxy. A constrained proxy may exist only as a migration/recovery path for allowlisted hosts and bounded images.

## Evidence And Constraints

- Raindrop exposes `cover` and `media[].link`, permits updating or uploading a cover, but does not guarantee cover URL permanence.[^raindrop-fields][^raindrop-single]
- Raindrop Web Archive is private, can fail on blocked sites, and is not a public image backend.[^raindrop-archive]
- Pixiv retains creator rights, prohibits unauthorized reproduction and mechanically excessive operations, and does not document stable third-party hotlinking or forged `Referer` as an integration.[^pixiv-terms]
- X media resolution requires its authenticated API; its policy requires displayed content to remain current and unavailable content to be removed.[^x-data][^x-policy]
- Vercel Functions have a 4.5 MB request/response body limit. Public Blob is intended for public images and avoids routing image bytes through the Function.[^function-limits][^blob]
- Vercel CDN retention is best effort, so cache is acceleration rather than preservation.[^cdn]

[The Pixiv bug](https://github.com/kriss-spy/daily-miku-base/issues/1) does not include enough network evidence to prove anti-hotlinking. The current code sends no Pixiv-specific headers and blindly forwards upstream content type, making either a 403 or a `200 text/html` error plausible (`api/hybrid.py:380-417`). Forging a `Referer` is not a supported or durable fix.

## Resolution Pipeline

1. Resolve the Daily Slot and reject conflicts rather than choosing one item.
2. Prefer a controlled Blob URL, then a Raindrop-uploaded cover, then another `cover`/`media` candidate handled by an explicit source adapter.
3. Require operator-provided, authorized bytes for Pixiv. Resolve X only through its official API and reconcile deletion/visibility changes.
4. For ingestion, allow only HTTPS and approved hosts; disable redirects or revalidate every hop and resolved address.
5. Bound declared and actual bytes, time, dimensions, pixels, and animation frames.
6. Require allowlisted raster types, verify magic bytes, decode, strip metadata, and re-encode where practical. Exclude SVG.
7. Hash normalized bytes and upload once as `images/<sha256>.<ext>` with an explicit content type.
8. Update Raindrop's cover reference while preserving the canonical artwork URL in `link`.

These controls address SSRF and malicious file risks identified by OWASP.[^owasp-ssrf][^owasp-upload]

## HTTP Contract

The mutable date route returns `307`, not a permanent redirect, because slot corrections and takedowns must propagate.[^rfc]

| Condition | Status |
| --- | ---: |
| Invalid date syntax | 400 |
| Empty slot or no image | 404 |
| Confirmed withdrawn image with tombstone | 410 |
| Upstream invalid/forbidden/missing and no mirror | 502 |
| Upstream timeout | 504 |
| Temporary service failure | 503 |

Never return upstream HTML/JSON as an image or silently replace a failed work with a `200` placeholder. Proxied bytes use the type established from validated content plus `X-Content-Type-Options: nosniff`.

Start the date resolver with short browser/CDN caching, for example `max-age=60`, `s-maxage=300`, and a carefully chosen stale window. Cache 404 briefly and use `no-store` for 5xx responses. Content-addressed Blob objects are immutable and may use long caching and ETags; only the date mapping remains mutable.[^vercel-cache][^blob]

## Operational Consequences

- Mirroring requires explicit reproduction authorization and takedown/deletion handling.
- Public Blob URLs are public to anyone who obtains them.[^blob]
- Use Vercel's supported `vercel` Python SDK for Blob access; current Blob documentation includes Python behavior and identifies Python SDK support alongside the TypeScript SDK.[^blob-sdk]
- Source disappearance does not break authorized mirrored bytes, but X policy and rights withdrawal can require deletion.
- The initializer should validate or mirror existing legacy covers separately and report unavailable images before cutover.

[^raindrop-fields]: [Raindrop API fields](https://developer.raindrop.io/v1/raindrops)
[^raindrop-single]: [Raindrop API single bookmark and cover upload](https://developer.raindrop.io/v1/raindrops/single)
[^raindrop-archive]: [Raindrop Web Archive](https://help.raindrop.io/web-archive)
[^pixiv-terms]: [Pixiv Terms of Use](https://policies.pixiv.net/en.html)
[^x-data]: [X API data dictionary](https://docs.x.com/x-api/fundamentals/data-dictionary)
[^x-policy]: [X Developer Policy](https://docs.x.com/developer-terms/policy)
[^function-limits]: [Vercel Function limits](https://vercel.com/docs/functions/limitations)
[^blob]: [Vercel Blob public storage](https://vercel.com/docs/vercel-blob/public-storage)
[^cdn]: [Vercel CDN cache limits](https://vercel.com/docs/caching/cdn-cache#limits)
[^owasp-ssrf]: [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
[^owasp-upload]: [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
[^rfc]: [RFC 9110, 307 Temporary Redirect](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.8)
[^vercel-cache]: [Vercel CDN cache criteria](https://vercel.com/docs/caching/cdn-cache#cacheable-response-criteria)
[^blob-sdk]: [Vercel Blob SDK](https://vercel.com/docs/vercel-blob/using-blob-sdk)
