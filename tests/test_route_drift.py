"""Contract tests for route-drift. Run: python -m pytest tests/ -q

Every test drives the real CLI over temp dirs; the red example committed
under .red/ pins all three drift rules with file:line evidence.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "route_drift.py")
RED = os.path.join(ROOT, ".red")

SPEC_CLEAN = """\
openapi: 3.0.0
info:
  title: Clean API
  version: 1.0.0
paths:
  /users:
    get:
      summary: List users
  /users/{id}:
    delete:
      summary: Delete a user
"""

CODE_CLEAN = """\
from flask import Flask
app = Flask(__name__)

@app.route("/users", methods=["GET"])
def list_users():
    return "ok"

@app.route("/users/<id>", methods=["DELETE"])
def drop_user(id):
    return "ok"
"""


def run_cli(*args):
    proc = subprocess.run([sys.executable, SCRIPT, *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True)
    return proc.returncode, proc.stdout, proc.stderr


def write(tmp, name, content):
    path = os.path.join(tmp, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def repo(tmp, spec=SPEC_CLEAN, code=CODE_CLEAN, code_name="app.py"):
    write(tmp, "openapi.yaml", spec)
    write(tmp, code_name, code)
    return tmp


def findings_json(tmp, *extra):
    code, out, _ = run_cli(tmp, "--json", *extra)
    return code, json.loads(out)


def test_match_is_clean(tmp_path):
    repo(str(tmp_path))
    code, out, _ = run_cli(str(tmp_path), "--no-color")
    assert code == 0, out
    assert "ok -- 0 drift finding(s)" in out


def test_missing_impl(tmp_path):
    spec = SPEC_CLEAN + "  /ghost:\n    get:\n      summary: Nowhere\n"
    repo(str(tmp_path), spec=spec)
    code, data = findings_json(str(tmp_path))
    assert code == 1
    rows = [f for f in data["findings"] if f["rule"] == "missing-impl"]
    assert len(rows) == 1
    assert rows[0]["path"] == "/ghost" and rows[0]["method"] == "get"
    assert rows[0]["where"].endswith("openapi.yaml:13")
    assert data["counts"]["missing-impl"] == 1


def test_missing_spec(tmp_path):
    repo(str(tmp_path),
         code=CODE_CLEAN + '\n@app.route("/extra", methods=["POST"])\ndef extra():\n    return "ok"\n')
    code, data = findings_json(str(tmp_path))
    assert code == 1
    rows = [f for f in data["findings"] if f["rule"] == "missing-spec"]
    assert len(rows) == 1
    assert rows[0]["path"] == "/extra" and rows[0]["method"] == "post"
    assert rows[0]["where"].endswith("app.py:12")
    assert data["counts"]["missing-spec"] == 1


def test_method_mismatch(tmp_path):
    repo(str(tmp_path),
         code=CODE_CLEAN.replace('methods=["DELETE"]', 'methods=["POST"]'))
    code, data = findings_json(str(tmp_path))
    assert code == 1
    rows = [f for f in data["findings"] if f["rule"] == "method-mismatch"]
    assert len(rows) == 1
    assert rows[0]["path"] == "/users/{id}"
    assert rows[0]["spec_methods"] == ["delete"]
    assert rows[0]["code_methods"] == ["post"]
    assert data["counts"]["method-mismatch"] == 1


def test_no_spec_file_is_usage_error(tmp_path):
    write(str(tmp_path), "app.py", CODE_CLEAN)
    code, _, err = run_cli(str(tmp_path))
    assert code == 2
    assert "no OpenAPI spec found" in err


def test_red_example_pins_all_three_rules():
    code, out, _ = run_cli(RED, "--json")
    assert code == 1, out
    data = json.loads(out)
    by_rule = {}
    for item in data["findings"]:
        by_rule.setdefault(item["rule"], []).append(item)
    assert sorted(by_rule) == ["method-mismatch", "missing-impl", "missing-spec"]
    assert len(data["findings"]) == 3
    assert by_rule["missing-impl"][0]["path"] == "/legacy"
    assert by_rule["missing-spec"][0]["path"] == "/cache"
    assert by_rule["method-mismatch"][0]["path"] == "/orders/{id}"
    for item in data["findings"]:
        assert item["where"], "every finding carries file:line evidence"
