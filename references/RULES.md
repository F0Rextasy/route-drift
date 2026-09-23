# Route rule catalogue

Input: a directory (or single file). The spec is auto-detected as the
first of `openapi.yaml/yml/json`, `spec.yaml/yml/json`,
`swagger.yaml/yml/json` under the target (`--spec FILE` overrides it).
Code files are `.js/.jsx/.ts/.tsx/.mjs/.cjs/.py` (skipping
`node_modules`, `.git`, `__pycache__`, `.venv`, `dist`, `build`).
No spec file -> usage error (exit 2); a spec with no `paths` mapping ->
parse error (exit 2). Unreadable code files are skipped, never fatal.

Spec parser: JSON via the stdlib `json` module; YAML via a minimal
indentation-based subset parser inside `route_drift.py` (mappings,
nested mappings, lists, block scalars, flow lists, quoted keys/values,
comments) -- stdlib only, no PyYAML, no network, deterministic.

Code parser: regex only (see `ROUTE_*` in the script). One route hit
keeps its `file:line`; comment lines (`//`, `#`, …) never count.

Canonical form: OpenAPI `{param}`, Express `:param`, and Flask
`<type:param>` all become `{param}`; repeated and trailing slashes
collapse (root `/` stays). `/users/:id` and `/users/{id}` are one
route, not two.

## Rules (all fail -- drift is a contract breach, never a warning)

| Rule | Condition |
| --- | --- |
| `missing-impl` | `(METHOD, path)` in the spec whose path exists in no code file |
| `missing-spec` | `(METHOD, path)` in code whose path exists in no spec entry |
| `method-mismatch` | same canonical path on both sides with different method sets -- one finding per path, naming both sets |

Exit 0 = spec and code agree, 1 = drift found, 2 = usage or parse error.
