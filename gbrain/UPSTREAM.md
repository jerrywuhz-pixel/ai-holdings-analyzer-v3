# GBrain Upstream Sync

This directory is not a direct checkout of upstream `garrytan/gbrain`. It is the AI Holdings 3.0 OpenClaw/Hermes adapter that keeps the same memory direction while using this project's Postgres schema and tenant model.

## Checked Upstreams

| Upstream | Observed version / commit | Date checked | Local action |
| --- | --- | --- | --- |
| `garrytan/gbrain` | `0.31.10`, commit `cb5bf1d3327b4d981775d35fa39b6a9abdbd0b79` | 2026-05-11 | Adopt runtime lessons, do not overwrite local adapter |
| `imphillip/gbrain-openclaw` | `0.1.0`, commit `44b6fb37995a3ee52baf2bea301c9eb9e5b60ea2` | 2026-05-11 | Keep as historical OpenClaw reference |

## Synced In This Workspace

- `@modelcontextprotocol/sdk` aligned to the newer upstream line: `^1.29.0`.
- `zod` is now an explicit dependency because `src/mcp-adapter.ts` imports it directly; it is pinned on the Zod 3 line for OpenAI SDK peer compatibility while still using the Zod 3/4-compatible two-argument `z.record(z.string(), z.unknown())` shape.
- `src/mcp-adapter.ts` was adjusted away from the old one-argument `z.record(...)` form that breaks on newer Zod signatures.
- `docker-compose.yml` now passes `GBRAIN_EMBEDDING_MODEL`, matching the adapter's environment variable.

## Not Directly Synced

The upstream `garrytan/gbrain` CLI has moved far beyond the 2.0 template, including cold-start import orchestration, multi-source routing fixes, doctor checks, PGLite/Postgres engine work, and remote/OAuth-related surfaces. Those are useful product lessons, but a direct code replacement would conflict with this system's:

- tenant/account isolation model,
- Supabase/Postgres migrations,
- OpenClaw channel binding contract,
- Hermes run contract and artifact registry,
- financial business-fact boundary.

Use `product-design-v3/33-gbrain-runtime-upgrade-plan.md` as the deployment and integration plan for making this adapter production-usable in 3.0.
