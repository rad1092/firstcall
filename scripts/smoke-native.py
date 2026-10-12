#!/usr/bin/env python3
"""Exercise an installed CLI against an original loopback API; no real credentials.

python3 scripts/smoke-native.py /path/to/firstcall-cli /new/evidence/folder
Optional --compare-fastmcp needs fastmcp==4.1.0 in the Python environment.
"""
import argparse
import asyncio
import hashlib
import http.server
import importlib.metadata
import json
import pathlib
import shutil
import subprocess
import threading

TOKEN = "synthetic-fixture-token-not-a-real-credential"
RESPONSE_MARKER = "synthetic-response-secret"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("cli", type=pathlib.Path)
parser.add_argument("output", type=pathlib.Path)
parser.add_argument("--compare-fastmcp", action="store_true")
args = parser.parse_args()
cli = args.cli.resolve(strict=True)
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
requests = []


class API(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        authorized = self.headers.get("Authorization") == f"Bearer {TOKEN}"
        requests.append({"method": self.command, "path": self.path, "authorized": authorized})
        status, body = 200, {"id": "fixture", "name": "Synthetic user", "api_key": RESPONSE_MARKER}
        if not authorized:
            status, body = 401, {"error": "fixture API requires a bearer token"}
        elif self.path == "/users/redirect":
            self.send_response(302)
            self.send_header("Location", "/admin/escaped")
            self.end_headers()
            return
        elif self.path == "/users/large":
            body = {"text": "x" * 300_000}
        elif not self.path.startswith("/users/"):
            status, body = 404, {"error": "endpoint not allowed"}
        encoded = b"{broken json" if self.path == "/users/malformed" else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        self.do_GET()

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), API)
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f"http://127.0.0.1:{server.server_port}"
env = {"FIRSTCALL_BEARER_TOKEN": TOKEN}
steps = []


def run(label, command, input=None, environment=env):
    result = subprocess.run([str(cli), *map(str, command)], input=input, env=environment,
                            text=True, capture_output=True, timeout=40)
    assert TOKEN not in result.stdout + result.stderr, label
    (out / f"{label}.stdout").write_text(result.stdout)
    (out / f"{label}.stderr").write_text(result.stderr)
    steps.append({"step": label, "exit": result.returncode})
    return result


def rpc(package, arguments, environment=env, allow_write=False):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "synthetic-validation", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "find_user", "arguments": arguments}},
    ]
    result = run(f"rpc-{len(steps)}", ["serve", "--package", package] +
                 (["--allow-mutating"] if allow_write else []),
                 "\n".join(map(json.dumps, messages)) + "\n", environment)
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    return result, responses


def digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


async def compare():
    import httpx2
    from fastmcp import Client, FastMCP
    from fastmcp.server.providers.openapi import RouteMap, MCPType
    operation = {"operationId": "find_user", "summary": "Look up a synthetic user", "parameters": [
        {"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "responses": {"200": {"description": "Synthetic result", "content": {
            "application/json": {"schema": {"type": "object", "additionalProperties": True}}}}}}
    spec = {"openapi": "3.0.3", "info": {"title": "Synthetic API", "version": "1"},
            "servers": [{"url": origin}], "paths": {"/users/{user_id}": {"get": operation},
            "/admin/reset": {"post": {"operationId": "reset_fixture", "responses": {"200": {"description": "Reset"}}}}}}
    (out / "openapi.json").write_text(json.dumps(spec, indent=2))
    comparisons = []
    for restricted in (False, True):
        async with httpx2.AsyncClient(base_url=origin, headers={"Authorization": f"Bearer {TOKEN}"},
                                      follow_redirects=False, timeout=30) as http:
            maps = [RouteMap(methods=["GET"], pattern=r"^/users/\{user_id\}$", mcp_type=MCPType.TOOL),
                    RouteMap(mcp_type=MCPType.EXCLUDE)] if restricted else None
            mcp = FastMCP.from_openapi(openapi_spec=spec, client=http, name="Fixture", route_maps=maps)
            async with Client(mcp) as client:
                tools = await client.list_tools()
                result = await client.call_tool("find_user", {"user_id": "fixture"}, raise_on_error=False)
                rendered = "\n".join(getattr(item, "text", "") for item in result.content)
                assert not result.is_error
                comparisons.append({"restricted": restricted, "tools": [t.name for t in tools],
                                    "auth_argument_exposed": any("token" in str(t.input_schema) for t in tools),
                                    "response_marker_visible": RESPONSE_MARKER in rendered})
    async with httpx2.AsyncClient(base_url=origin) as http:
        mcp = FastMCP.from_openapi(openapi_spec=spec, client=http, name="Missing fixture auth")
        async with Client(mcp) as client:
            result = await client.call_tool("find_user", {"user_id": "fixture"}, raise_on_error=False)
            missing = {"is_error": result.is_error,
                       "text": "\n".join(getattr(item, "text", "") for item in result.content)}
    return {"version": importlib.metadata.version("fastmcp"), "cases": comparisons,
            "missing_auth": missing, "transport": "FastMCP in-memory client to generated tools; real loopback HTTP",
            "custom_redaction_added": False}


try:
    recipe = {"id": None, "name": "Find user", "method": "GET",
              "url_template": origin + "/users/{{user_id}}", "headers_template": [], "query_template": [],
              "body_template": "none", "auth_style": {"bearer": {"token_slot": "bearer_token", "header_name": "Authorization"}},
              "slots": [{"name": name, "location": location, "required": True, "current_value": value,
                         "description": description, "confidence": "high"} for name, location, value, description in [
                             ("user_id", "path", "fixture", "Synthetic user identifier"),
                             ("bearer_token", "auth", None, "Bearer token from environment")]],
              "last_success_at": None, "last_success_status": None}
    recipe_path, verified = out / "recipe.json", out / "verified.json"
    recipe_path.write_text(json.dumps(recipe))
    tool_path = out / "tool.json"
    tool_path.write_text(json.dumps({"schema_version": 1, "name": "find_user", "title": "Find fixture user",
        "description": "Look up a synthetic user and return its display name.", "input_schema": {
            "type": "object", "properties": {"user_id": {"type": "string", "description": "Synthetic user ID"}},
            "required": ["user_id"], "additionalProperties": False}}))
    assert run("verify", ["verify", "--recipe-json", recipe_path, "--out", verified, "--json"]).returncode == 0
    package = out / "original tool"
    assert run("export", ["package-native", "--recipe-json", verified, "--tool-json", tool_path, "--out", package]).returncode == 0
    before = digest(package)
    assert run("reject-overwrite", ["package-native", "--recipe-json", verified, "--tool-json", tool_path, "--out", package]).returncode != 0
    assert digest(package) == before
    moved = out / "moved tool"
    package.rename(moved)
    assert run("connect", ["connect", "--package", moved]).returncode == 0
    config = json.loads((out / "connect.stdout").read_text())["mcpServers"]["find_user"]
    assert config["args"][2] == str(moved)
    assert config["env"]["FIRSTCALL_BEARER_TOKEN"] == ""
    for repetition in range(3):
        result, responses = rpc(moved, {"user_id": "fixture"})
        assert result.returncode == 0 and not responses[-1]["result"].get("isError")
        assert RESPONSE_MARKER not in result.stdout
        schema = responses[1]["result"]["tools"][0]["inputSchema"]
        assert "bearer_token" not in schema["properties"]
    failures = {}
    for label, inputs, credentials in [
        ("traversal", {"user_id": "../admin"}, env),
        ("wrong-type", {"user_id": 42}, env),
        ("auth-in-arguments", {"user_id": "fixture", "bearer_token": TOKEN}, env),
        ("missing-auth", {"user_id": "fixture"}, {}),
        ("redirect", {"user_id": "redirect"}, env),
        ("large", {"user_id": "large"}, env),
        ("malformed", {"user_id": "malformed"}, env),
    ]:
        count = len(requests)
        result, responses = rpc(moved, inputs, credentials)
        assert result.returncode == 0 and responses[-1]["result"]["isError"], label
        assert RESPONSE_MARKER not in result.stdout
        if label in {"traversal", "wrong-type", "auth-in-arguments", "missing-auth"}:
            assert len(requests) == count, label
        failures[label] = responses[-1]["result"]
    assert not any(r["path"].startswith("/admin/") for r in requests)
    assert digest(moved) == before
    # A killed idle connection cannot rewrite package contents. This is not an
    # assertion that an in-flight HTTP request or remote mutation can be undone.
    idle = subprocess.Popen([str(cli), "serve", "--package", str(moved)], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    idle.terminate()
    idle.communicate(timeout=5)
    assert digest(moved) == before
    bad = out / "tampered tool"
    shutil.copytree(moved, bad)
    (bad / "policy.json").write_text("{}")
    rejected = run("tampered-connect", ["connect", "--package", bad])
    assert rejected.returncode != 0 and rejected.stdout == ""
    write_recipe = json.loads(verified.read_text())
    write_recipe["method"] = "POST"
    write_recipe["last_success_at"] = None
    write_recipe["last_success_status"] = None
    write_path, write_verified = out / "write.json", out / "write-verified.json"
    write_path.write_text(json.dumps(write_recipe))
    assert run("write-verify-denied", ["verify", "--recipe-json", write_path]).returncode != 0
    assert run("write-verify", ["verify", "--recipe-json", write_path, "--allow-mutating", "--out", write_verified]).returncode == 0
    write_package = out / "write tool"
    export_args = ["package-native", "--recipe-json", write_verified, "--tool-json", tool_path, "--out", write_package]
    assert run("write-export-denied", export_args).returncode != 0
    assert not write_package.exists()
    assert run("write-export", export_args + ["--allow-mutating"]).returncode == 0
    assert run("write-connect-denied", ["connect", "--package", write_package]).returncode != 0
    assert run("write-connect", ["connect", "--package", write_package, "--allow-mutating"]).returncode == 0
    result, _ = rpc(write_package, {"user_id": "fixture"})
    assert result.returncode != 0
    result, responses = rpc(write_package, {"user_id": "fixture"}, allow_write=True)
    assert result.returncode == 0 and not responses[-1]["result"].get("isError")
    comparison = asyncio.run(compare()) if args.compare_fastmcp else None
    report = {"cli_version": run("version", ["version"]).stdout.strip(),
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "firstcall": {"repeated_successes": 3, "failures": failures, "package_preserved": True},
              "fastmcp": comparison, "requests": requests, "steps": steps}
    (out / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": "passed", "cli_version": report["cli_version"],
                      "firstcall_regressions": len(failures), "fastmcp": comparison, "evidence": str(out)}))
finally:
    server.shutdown()
    server.server_close()
