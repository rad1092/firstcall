#!/usr/bin/env python3
"""Verify optional input omission through an installed CLI and actual MCP/HTTP.
Usage: python3 scripts/smoke-optional.py /path/to/firstcall-cli /new/output
Uses only a self-contained loopback fixture and Python's standard library.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

cli = Path(sys.argv[1]).resolve(strict=True)
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
requests = []
results = []


class API(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append({"path": self.path, "note": self.headers.get("X-Note")})
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), API)
threading.Thread(target=server.serve_forever, daemon=True).start()


def run(label, command, stdin=None, hidden_environment=False):
    environment = {"PATH": os.environ.get("PATH", "")}
    if hidden_environment:
        environment["FIRSTCALL_SLOT_OPTIONAL_VALUE"] = "must-not-be-used"
    result = subprocess.run([str(cli), *map(str, command)], input=stdin,
                            env=environment, text=True, capture_output=True, timeout=30)
    (out / (label + ".stdout")).write_text(result.stdout)
    (out / (label + ".stderr")).write_text(result.stderr)
    assert result.returncode == 0, (label, result.stdout, result.stderr)
    return result


def expected_request(location, filled):
    return {"path": "/fixture?limit=3" if location == "query" and filled else "/fixture",
            "note": "3" if location == "header" and filled else None}


try:
    for location in ["query", "header"]:
        for filled in [False, True]:
            label = location + ("-filled" if filled else "-empty")
            field = {"key": "limit" if location == "query" else "X-Note",
                     "value": "{{optional_value}}", "required": False,
                     "description": "Optional fixture input", "confidence": "high"}
            recipe = {"id": None, "name": "Optional fixture", "method": "GET",
                      "url_template": f"http://127.0.0.1:{server.server_port}/fixture",
                      "headers_template": [field] if location == "header" else [],
                      "query_template": [field] if location == "query" else [],
                      "body_template": "none", "auth_style": "none",
                      "slots": [{"name": "optional_value", "location": location,
                                 "required": False, "current_value": "3" if filled else None,
                                 "description": "May be omitted", "confidence": "high"}],
                      "last_success_at": None, "last_success_status": None}
            source, verified = out / (label + ".json"), out / (label + "-verified.json")
            source.write_text(json.dumps(recipe))
            count = len(requests)
            run(label + "-verify", ["verify", "--recipe-json", source, "--out", verified, "--json"])
            assert requests[count:] == [expected_request(location, filled)]
            tool = out / (label + "-tool.json")
            tool.write_text(json.dumps({"schema_version": 1, "name": "optional_fixture",
                "title": "Optional fixture", "description": "Read a synthetic fixture with an optional input.",
                "input_schema": {"type": "object", "properties": {
                    "optional_value": {"type": "string", "description": "An optional fixture input"}},
                    "required": [], "additionalProperties": False}}))
            package = out / (label + "-package")
            run(label + "-export", ["package-native", "--recipe-json", verified,
                                   "--tool-json", tool, "--out", package])
            # Each call gets a fresh connection; back-to-back calls on one
            # connection are intentionally subject to the runtime's rate limit.
            for call_filled in [False, True]:
                arguments = {"optional_value": "3"} if call_filled else {}
                messages = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "optional-regression", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                        "name": "optional_fixture", "arguments": arguments}},
                ]
                count = len(requests)
                response = run(label + ("-mcp-filled" if call_filled else "-mcp-empty"),
                               ["serve", "--package", package],
                               "\n".join(map(json.dumps, messages)) + "\n", hidden_environment=True)
                replies = {r["id"]: r for r in map(json.loads, response.stdout.splitlines())}
                assert not replies[3]["result"].get("isError"), replies[3]
                assert replies[2]["result"]["tools"][0]["inputSchema"].get("required", []) == []
                assert requests[count:] == [expected_request(location, call_filled)]
            results.append({"case": label, "verify": "passed", "mcpOmittedAndSupplied": "passed"})
    report = {"passed": True, "cliSha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "results": results, "requests": requests}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "cases": len(results), "httpRequests": len(requests)}))
finally:
    server.shutdown()
    server.server_close()
