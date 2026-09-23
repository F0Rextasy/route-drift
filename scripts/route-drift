#!/usr/bin/env python3
"""route-drift -- print the drift between an OpenAPI spec and the routes in code.

Reads an OpenAPI spec (YAML subset parser, stdlib only -- no PyYAML, no pip,
no network) plus regex-extracted route definitions from code files, maps
OpenAPI ``{param}`` and Express ``:param`` styles to one canonical form, and
reports every mismatch with file:line evidence:

  missing-impl    (METHOD, path) in the spec, path implemented nowhere
  missing-spec    (METHOD, path) in code, path absent from the spec
  method-mismatch (METHOD, path) on one side while the same path exists
                  on the other side with different methods

Route sources understood: Express-style ``app.get('/x')`` calls, Express
``router.route('/x').get(...)`` chains, Fastify calls and
``fastify.route({method, url})``, Flask ``@app.route`` / ``@app.get``
decorators, Next.js ``pages/api`` / ``app/api`` file routes, and any generic
``res.get('/x')``-shaped call whose first argument starts with ``/``.

Exit 0 = spec and code agree, 1 = drift found, 2 = usage or parse error.
"""

import argparse
import json
import os
import re
import sys

METHODS = ("get", "post", "put", "delete", "patch", "head", "options", "trace")
METHOD_SET = set(METHODS)

SPEC_NAMES = ("openapi.yaml", "openapi.yml", "openapi.json",
              "spec.yaml", "spec.yml", "spec.json",
              "swagger.yaml", "swagger.yml", "swagger.json")

CODE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
             "dist", "build", ".tox", ".pytest_cache"}

RULES = {
    "missing-impl": "spec operation has no code implementation -- implement it or drop it from the spec",
    "missing-spec": "code route has no spec entry -- document it or delete it",
    "method-mismatch": "path exists on both sides with different methods -- align the verbs",
}

BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"


def paint(text, *codes, color=True):
    if not color:
        return text
    return "".join(codes) + text + RESET


# ---------------------------------------------------------------------------
# Minimal YAML subset parser (mappings, nested mappings, lists, block scalars,
# flow lists, quoted keys/values, comments). Only what an OpenAPI paths
# document needs -- values stay strings.
# ---------------------------------------------------------------------------

def _strip_inline_comment(text):
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in (" ", "\t")):
            return text[:i].rstrip()
    return text


def _unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return text


def _split_key(text):
    """Split 'key: value' on the first colon outside quotes. Else None."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ":":
            after = text[i + 1:i + 2]
            if after in ("", " ", "\t"):
                return text[:i].strip(), text[i + 1:].strip()
    return None


def _flow_list(value):
    """Parse '[a, b]' (quotes respected). Returns list or None."""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return None
    items, current, quote = [], "", None
    for ch in value[1:-1]:
        if quote:
            current += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            current += ch
        elif ch == ",":
            items.append(_unquote(current))
            current = ""
        else:
            current += ch
    if current.strip() or items:
        items.append(_unquote(current))
    return [_unquote(i) for i in items if i.strip() or len(items) == 1 and not i.strip()]


def parse_yaml_subset(text):
    rows = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        content = _strip_inline_comment(stripped).strip()
        if content:
            rows.append((indent, content))
    pos = [0]

    def peek():
        return rows[pos[0]] if pos[0] < len(rows) else None

    def parse_node(parent_indent):
        cur = peek()
        if cur is None or cur[0] <= parent_indent:
            return None
        if cur[1] == "-" or cur[1].startswith("- "):
            return parse_list(cur[0])
        return parse_map(cur[0])

    def parse_value(value, cur_indent):
        if value in ("|", ">"):
            buf = []
            while True:
                nxt = peek()
                if nxt is None or nxt[0] <= cur_indent:
                    break
                buf.append(nxt[1])
                pos[0] += 1
            return "\n".join(buf) if value == "|" else " ".join(buf)
        if value == "":
            return parse_node(cur_indent)
        flow = _flow_list(value)
        if flow is not None:
            return flow
        return _unquote(value)

    def parse_map(indent):
        mapping = {}
        while True:
            cur = peek()
            if cur is None or cur[0] != indent:
                break
            pair = _split_key(cur[1])
            if pair is None or not pair[0]:
                pos[0] += 1
                continue
            key, value = pair
            pos[0] += 1
            mapping[_unquote(key)] = parse_value(value, indent)
        return mapping

    def parse_list(indent):
        items = []
        while True:
            cur = peek()
            if cur is None or cur[0] != indent:
                break
            content = cur[1]
            if not (content == "-" or content.startswith("- ")):
                break
            pos[0] += 1
            rest = content[1:].strip()
            if not rest:
                items.append(parse_node(indent))
                continue
            pair = _split_key(rest)
            if pair is not None and pair[0]:
                mapping = {_unquote(pair[0]): parse_value(pair[1], indent)}
                while True:
                    nxt = peek()
                    if nxt is None or nxt[0] <= indent:
                        break
                    if nxt[1] == "-" or nxt[1].startswith("- "):
                        break
                    pair2 = _split_key(nxt[1])
                    pos[0] += 1
                    if pair2 is None or not pair2[0]:
                        continue
                    mapping[_unquote(pair2[0])] = parse_value(pair2[1], nxt[0])
                items.append(mapping)
            else:
                items.append(_unquote(rest))
        return items

    node = parse_node(-1)
    return node if node is not None else {}


# ---------------------------------------------------------------------------
# Canonical route form: OpenAPI {param}, Express :param and Flask <type:param>
# all become {param}; trailing slashes drop (root "/" stays).
# ---------------------------------------------------------------------------

def canonical(path):
    text = path.strip().replace("\\", "/")
    text = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", text)
    text = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", text)
    text = re.sub(r"/{2,}", "/", text)
    if len(text) > 1:
        text = text.rstrip("/")
    if not text.startswith("/"):
        text = "/" + text
    return text


# ---------------------------------------------------------------------------
# Spec loading: JSON via stdlib, YAML via the subset parser above.
# ---------------------------------------------------------------------------

def find_spec(target):
    if os.path.isfile(target):
        target = os.path.dirname(os.path.abspath(target)) or "."
    for name in SPEC_NAMES:
        candidate = os.path.join(target, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def load_spec(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        return None, "cannot read spec %s: %s" % (path, exc)
    if path.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            return None, "cannot parse spec %s: %s" % (path, exc)
    else:
        try:
            data = parse_yaml_subset(text)
        except (ValueError, IndexError, RecursionError) as exc:
            return None, "cannot parse spec %s: %s" % (path, exc)
        if not isinstance(data, dict):
            return None, "cannot parse spec %s: top level is not a mapping" % path
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        return None, "cannot parse spec %s: no 'paths' mapping found" % path
    return (data, text), None


def spec_operations(data):
    """Canonical path -> set of spec methods."""
    ops = {}
    for path, methods in (data.get("paths") or {}).items():
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        found = set()
        if isinstance(methods, dict):
            for method in methods:
                low = str(method).lower()
                if low in METHOD_SET:
                    found.add(low)
        ops[canonical(path)] = found
    return ops


def spec_line_index(text, is_json):
    """(path -> line, (path, method) -> line) for evidence output."""
    path_lines, op_lines = {}, {}
    if is_json:
        matches = list(re.finditer(r'"(/[^"]*)"\s*:', text))
        for i, match in enumerate(matches):
            path = canonical(match.group(1))
            if path in path_lines:
                continue
            line = text.count("\n", 0, match.start()) + 1
            path_lines[path] = line
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            for mm in re.finditer(r'"(get|post|put|delete|patch|head|options|trace)"\s*:',
                                  text[match.end():end], re.I):
                key = (path, mm.group(1).lower())
                if key not in op_lines:
                    op_lines[key] = text.count("\n", 0, match.end() + mm.start()) + 1
        return path_lines, op_lines
    lines = text.splitlines()
    paths_at = None
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if re.match(r"^['\"]?paths['\"]?\s*:", stripped):
            paths_at = len(raw) - len(raw.lstrip(" \t"))
            break
    if paths_at is None:
        return path_lines, op_lines
    cur, path_indent = None, None
    for i, raw in enumerate(lines):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        if indent <= paths_at:
            if cur is not None and indent <= paths_at:
                pass
            continue
        content = _strip_inline_comment(raw.strip()).strip()
        pair = _split_key(content)
        if pair is None:
            continue
        key = _unquote(pair[0])
        if key.startswith("/"):
            cur, path_indent = canonical(key), indent
            path_lines.setdefault(cur, i + 1)
        elif cur is not None and path_indent is not None and indent > path_indent \
                and key.lower() in METHOD_SET:
            op_lines.setdefault((cur, key.lower()), i + 1)
        elif indent <= (path_indent if path_indent is not None else paths_at):
            cur, path_indent = None, None
    return path_lines, op_lines


# ---------------------------------------------------------------------------
# Code route extraction (regex per framework, every hit keeps its line).
# ---------------------------------------------------------------------------

CALL_RE = re.compile(
    r"([A-Za-z_$][\w$]*)\s*\.\s*(get|post|put|delete|patch|options|head|all)"
    r"\s*\(\s*['\"`]([^'\"`]+?)['\"`]")
FLASK_ROUTE_RE = re.compile(
    r"@[A-Za-z_][\w.]*\.route\s*\(\s*['\"`]([^'\"`]+?)['\"`]"
    r"(?:\s*,\s*methods\s*=\s*\[([^\]]*)\])?")
FLASK_SHORT_RE = re.compile(
    r"@[A-Za-z_][\w.]*\.(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`]+?)['\"`]")
FASTIFY_ROUTE_RE = re.compile(r"\.route\s*\(\s*\{(.*?)\}\s*\)", re.S)
EXPRESS_CHAIN_RE = re.compile(r"\.route\s*\(\s*['\"`]([^'\"`]+?)['\"`]\s*\)")
CHAIN_VERB_RE = re.compile(r"\.(get|post|put|delete|patch|options|head|all)\s*\(")

COMMENT_PREFIXES = ("//", "#", "*", "/*", "<!--", "%", "%%", "--")


def _is_comment(line):
    return line.lstrip().startswith(COMMENT_PREFIXES)


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _method_list(raw):
    methods = {m.lower() for m in re.findall(r"[A-Za-z]+", raw or "")
               if m.lower() in METHOD_SET}
    return methods or {"get"}


def extract_file(path, rel):
    """Return [(method, canonical_path, line)] for one code file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return []
    is_js = os.path.splitext(path)[1].lower() in JS_EXTS
    is_py = path.endswith(".py")
    hits = []
    lines = text.splitlines()

    for i, line in enumerate(lines, 1):
        if _is_comment(line):
            continue
        for match in CALL_RE.finditer(line):
            raw_path = match.group(3).strip()
            if not raw_path.startswith("/"):
                continue
            method = match.group(2).lower()
            if method == "all":
                for expanded in ("get", "post", "put", "delete", "patch"):
                    hits.append((expanded, canonical(raw_path), i))
            else:
                hits.append((method, canonical(raw_path), i))
        if is_py:
            for match in FLASK_ROUTE_RE.finditer(line):
                raw_path = match.group(1).strip()
                if not raw_path.startswith("/"):
                    continue
                methods = match.group(2)
                if methods is None:
                    found = {"get"}
                else:
                    found = _method_list(methods)
                for method in found:
                    hits.append((method, canonical(raw_path), i))
            for match in FLASK_SHORT_RE.finditer(line):
                raw_path = match.group(2).strip()
                if not raw_path.startswith("/"):
                    continue
                hits.append((match.group(1).lower(), canonical(raw_path), i))

    if is_js:
        for match in FASTIFY_ROUTE_RE.finditer(text):
            body = match.group(1)
            url = re.search(r"url\s*:\s*['\"`]([^'\"`]+?)['\"`]", body)
            if not url or not url.group(1).startswith("/"):
                continue
            meth = re.search(
                r"method\s*:\s*(?:\[([^\]]*)\]|['\"`]([^'\"`]+)['\"`])", body)
            if meth:
                found = _method_list(meth.group(1) or meth.group(2) or "")
            else:
                found = {"get"}
            line = _line_of(text, match.start())
            for method in found:
                hits.append((method, canonical(url.group(1)), line))
        for match in EXPRESS_CHAIN_RE.finditer(text):
            tail = text[match.end():match.end() + 1500]
            if not tail.lstrip().startswith("."):
                continue
            tail = tail.split(";", 1)[0]
            route_path = canonical(match.group(1))
            if not route_path.startswith("/"):
                continue
            for verb in CHAIN_VERB_RE.finditer(tail):
                method = verb.group(1).lower()
                line = _line_of(text, match.end() + verb.start())
                if method == "all":
                    for expanded in ("get", "post", "put", "delete", "patch"):
                        hits.append((expanded, route_path, line))
                else:
                    hits.append((method, route_path, line))

    route = nextjs_route(rel)
    if route is not None:
        for method in nextjs_methods(text, rel):
            hits.append((method, route, 1))

    seen = set()
    unique = []
    for method, route_path, line in hits:
        key = (line, method, route_path)
        if key not in seen:
            seen.add(key)
            unique.append((method, route_path, line))
    return unique


def compare(spec_ops, code, spec_file, path_lines, op_lines):
    findings = []
    for path in sorted(set(spec_ops) | set(code)):
        spec_methods = spec_ops.get(path, set())
        code_entry = code.get(path, {})
        code_methods = set(code_entry)
        if spec_methods and code_methods and spec_methods != code_methods:
            only_code = sorted(code_methods - spec_methods)
            code_refs = ["%s:%d" % ref
                         for m in only_code for ref in code_entry[m][:1]]
            shared_refs = ["%s:%d" % ref
                           for m in sorted(code_methods & spec_methods)
                           for ref in code_entry[m][:1]]
            spec_ref = "%s:%d" % (spec_file, path_lines.get(path, 0))
            where = code_refs[0] if code_refs else spec_ref
            findings.append({
                "rule": "method-mismatch", "method": None, "path": path,
                "where": where,
                "spec": {"file": spec_file, "line": path_lines.get(path, 0)},
                "code": [{"file": f, "line": n}
                         for m in only_code for f, n in code_entry[m][:1]],
                "spec_methods": sorted(spec_methods),
                "code_methods": sorted(code_methods),
                "detail": "%s: spec declares [%s], code implements [%s] "
                          "(spec %s; code %s)" % (
                              path,
                              ", ".join(m.upper() for m in sorted(spec_methods)),
                              ", ".join(m.upper() for m in sorted(code_methods)),
                              spec_ref, ", ".join(code_refs + shared_refs)),
            })
            continue
        for method in sorted(spec_methods - code_methods):
            line = op_lines.get((path, method)) or path_lines.get(path, 0)
            findings.append({
                "rule": "missing-impl", "method": method, "path": path,
                "where": "%s:%d" % (spec_file, line),
                "spec": {"file": spec_file, "line": line},
                "code": [],
                "detail": "%s %s in spec -- no code implements %s" % (
                    method.upper(), path, path),
            })
        for method in sorted(code_methods - spec_methods):
            refs = code_entry[method]
            findings.append({
                "rule": "missing-spec", "method": method, "path": path,
                "where": "%s:%d" % refs[0],
                "spec": None,
                "code": [{"file": f, "line": n} for f, n in refs],
                "detail": "%s %s in code -- no spec entry for %s" % (
                    method.upper(), path, path),
            })
    findings.sort(key=lambda f: (f["path"], f["rule"], f["method"] or ""))
    return findings


def nextjs_route(rel):
    parts = rel.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part == "api" and i > 0 and parts[i - 1] in ("pages", "app"):
            rest = parts[i + 1:]
            break
    else:
        return None
    if not rest:
        return None
    *dirs, filename = rest
    stem = filename.rsplit(".", 1)[0]
    if stem != "route":
        dirs = dirs + [stem]
    segments = []
    for chunk in dirs:
        if chunk in ("", "index"):
            continue
        chunk = re.sub(r"\[\.\.\.([^\]]+)\]", r"{\1}", chunk)
        chunk = re.sub(r"\[([^\]]+)\]", r"{\1}", chunk)
        segments.append(chunk)
    return canonical("/" + "/".join(segments))


def nextjs_methods(text, rel):
    is_app_router = "/app/api/" in rel.replace("\\", "/")
    if not is_app_router:
        return {"get"}
    found = {m.lower() for m in
             re.findall(r"export\s+(?:async\s+)?function\s+"
                        r"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b", text)}
    found |= {m.lower() for m in
              re.findall(r"export\s+const\s+"
                         r"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b", text)}
    return found or {"get"}


def collect_code(target):
    """Walk target for code files. Returns {canon: {method: [(rel, line)]}}."""
    if os.path.isfile(target):
        files = [target]
    else:
        files = []
        for root, dirs, names in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in CODE_EXTS:
                    files.append(os.path.join(root, name))
    code = {}
    for path in files:
        rel = os.path.relpath(path, target if os.path.isdir(target)
                              else os.path.dirname(os.path.abspath(target)))
        rel = rel.replace(os.sep, "/")
        for method, route_path, line in extract_file(path, rel):
            code.setdefault(route_path, {}).setdefault(method, []).append((rel, line))
    return code


# ---------------------------------------------------------------------------
# Render + main.
# ---------------------------------------------------------------------------
def render_text(findings, spec_count, code_count, spec_ops, code_ops, color):
    for item in findings:
        print("%s  %s  %-15s %s" % (
            item["where"],
            paint("FAIL", RED, BOLD, color=color),
            item["rule"], item["detail"]))
    if findings:
        print()
    tail = "%d spec path(s) (%d operation(s)), %d code path(s) (%d operation(s))" % (
        spec_count, spec_ops, code_count, code_ops)
    if findings:
        print(paint("route-drift: %d drift finding(s) across %s"
                    % (len(findings), tail), BOLD, RED, color=color))
        print(paint("route-drift: update the spec or the routes -- "
                    "drift is a contract breach", BOLD, color=color))
    else:
        print(paint("route-drift: ok -- 0 drift finding(s) across %s" % tail,
                    BOLD, GREEN, color=color))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="route-drift",
        description="Print drift between an OpenAPI spec and route "
                    "definitions in code. Exit 1 on drift, 0 when clean.")
    parser.add_argument("path", nargs="?", default=".",
                        help="directory (or file) to scan for an OpenAPI spec "
                             "and code routes (default .)")
    parser.add_argument("--spec", metavar="FILE",
                        help="explicit spec file (default: auto-detect "
                             "openapi.yaml/yml/json under PATH)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report on stdout")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)
    color = not args.no_color and sys.stdout.isatty()
    as_json = args.json or args.format == "json"

    target = args.path
    if not os.path.exists(target):
        print("route-drift: no such file or directory: %s" % target,
              file=sys.stderr)
        return 2

    spec_path = args.spec
    if spec_path is None:
        spec_path = find_spec(target)
        if spec_path is None:
            print("route-drift: no OpenAPI spec found under %s "
                  "(looked for %s; pass --spec FILE)"
                  % (target, ", ".join(SPEC_NAMES)), file=sys.stderr)
            return 2
    if not os.path.isfile(spec_path):
        print("route-drift: no such spec file: %s" % spec_path, file=sys.stderr)
        return 2

    loaded, error = load_spec(spec_path)
    if error is not None:
        print("route-drift: %s" % error, file=sys.stderr)
        return 2
    data, text = loaded

    base = target if os.path.isdir(target) else os.path.dirname(
        os.path.abspath(target))
    spec_rel = os.path.relpath(spec_path, base).replace(os.sep, "/")

    spec_ops = spec_operations(data)
    path_lines, op_lines = spec_line_index(text, spec_path.endswith(".json"))
    code = collect_code(target)
    # Never mistake the spec for code.
    code.pop(canonical(spec_rel), None)

    findings = compare(spec_ops, code, spec_rel, path_lines, op_lines)
    spec_op_count = sum(len(v) for v in spec_ops.values())
    code_op_count = sum(len(v) for v in code.values())

    if as_json:
        print(json.dumps({
            "ok": not findings,
            "counts": {
                "missing-impl": sum(1 for f in findings if f["rule"] == "missing-impl"),
                "missing-spec": sum(1 for f in findings if f["rule"] == "missing-spec"),
                "method-mismatch": sum(1 for f in findings if f["rule"] == "method-mismatch"),
                "spec_paths": len(spec_ops),
                "code_paths": len(code),
                "spec_ops": spec_op_count,
                "code_ops": code_op_count,
            },
            "findings": findings,
        }, indent=2, sort_keys=False))
    else:
        render_text(findings, len(spec_ops), len(code),
                    spec_op_count, code_op_count, color)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
