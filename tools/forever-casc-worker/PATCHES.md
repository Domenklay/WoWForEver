# Independent worker and upstream provenance

This executable is a separate GPL-3.0-or-later program. Its TACT/CASC modules,
HTTP layer and BPSV implementation come from Lightforge commit
360ff4c8dce06b9cedbb863088fdfc8842a6c521; see UPSTREAM.json and LICENSE.
No game payload, artwork, credentials or launcher sessions are included.

Changes from that source:

- Only the content engine is included. Product identity, filesystem helpers,
  error formatting and CLI/JSON transport are small worker-local adapters.
- Version resolution is pinned to the user's verified wowf 70658 BuildConfig
  and CDNConfig; live versions/bgdl cannot switch a client behind the server.
- Sources come from the supplied Nvord 2.0 journal and native client Tact logs.
  Explicit source order is retained; content hashes remain mandatory.
- No Agent registry/product.db integration, game execution or login settings.
- Windows regular-file store lock and positional reads; atomic file writes
  keep platform-specific permissions behind cfg(unix).
- The upstream product-config fixture tests are omitted (no game JSON copied).
  Unix-only build-info permission tests are excluded on Windows.

The main Multi application communicates with this executable using JSON lines;
the worker does not link into the launcher. The distributable includes this
program's complete corresponding source and GPL text alongside its binary.
