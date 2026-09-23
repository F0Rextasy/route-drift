---
name: route-drift
description: Prints drift between an OpenAPI spec and route definitions in code -- spec operations with no implementation, code routes with no spec entry, and method mismatches on the same path, every finding with file:line evidence. Understands Express, Fastify, Flask, Next.js, and generic res.get('/x') calls; maps {param}/:param/<type:param> to one canonical form. Use before shipping API changes, in CI on every PR that touches routes or the spec, or when consumers report endpoints the docs never mention. Exit 1 = drift found; exit 2 = no spec / bad usage.
license: MIT
compatibility: Requires Python 3.8+ stdlib only -- no dependencies, no network. Ships its own YAML subset parser (no PyYAML). Works in Claude Code, Codex, Cursor, and any Agent Skills compatible client.
metadata:
  author: F0Rextasy
  version: "1.0"
---

# route-drift

Your OpenAPI spec lies to your face — this gate prints the drift: spec
operations nobody implements, code routes nobody documents, and verbs
that disagree on the same path. Every finding carries `file:line`
evidence on both sides.

## The one rule

You may not ship a spec that disagrees with the code:

```bash
python route_drift.py myproject --no-color
```

- **exit 1** - drift found (`missing-impl`, `missing-spec`,
  `method-mismatch`).
- **exit 0** - spec and code agree.
- **exit 2** - usage: no spec found, unreadable spec, no `paths`
  mapping, bad flags.

## Protocol

1. **Point at a directory** (or a file): the spec is auto-detected as
   the first of `openapi.yaml/yml/json`, `spec.yaml/yml/json`,
   `swagger.yaml/yml/json` under the target; `--spec FILE` overrides it.
2. **Read findings** as `file:line  FAIL  rule  detail` — drift is a
   contract breach, never a warning.
3. **Fix the side that is wrong**: implement or drop the spec operation,
   document or delete the code route, align the verbs. `--json` for
   machines (`ok`, per-rule `counts`, `findings` with spec/code refs).

## Rules

| Rule | Fires when |
| --- | --- |
| `missing-impl` | `(METHOD, path)` in the spec whose path exists in no code file |
| `missing-spec` | `(METHOD, path)` in code whose path exists in no spec entry |
| `method-mismatch` | same canonical path on both sides with different method sets — one finding per path, naming both sets |

Canonical form: OpenAPI `{param}`, Express `:param`, and Flask
`<type:param>` all become `{param}`; trailing slashes drop. Route
sources: Express `app.get('/x')` + `router.route('/x').get(...)`
chains, Fastify calls + `route({method, url})`, Flask `@app.route` /
`@app.get` decorators, Next.js `pages/api` / `app/api` file routes,
generic `res.get('/x')` calls.

```console
$ python route_drift.py --json .red/
app.js:15  FAIL  missing-spec     DELETE /cache in code -- no spec entry for /cache
openapi.yaml:20  FAIL  missing-impl     GET /legacy in spec -- no code implements /legacy
app.js:12  FAIL  method-mismatch  /orders/{id}: spec declares [GET], code implements [POST] (spec openapi.yaml:22; code app.js:12)

route-drift: 3 drift finding(s) across 5 spec path(s) (7 operation(s)), 5 code path(s) (7 operation(s))
route-drift: update the spec or the routes -- drift is a contract breach
[exit 1]
```

## Reporting back

1. Counts: per-rule findings, spec paths/ops, code paths/ops.
2. Every finding: `file:line`, rule, detail with the other side's ref.
3. Command and exit code.
