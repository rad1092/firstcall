# FirstCall and FastMCP: one synthetic task

Choose FirstCall for a reviewed, single API operation that a recipient should
run from an installed native binary, with a bounded endpoint policy and redacted
results. Choose FastMCP when you want to build a Python MCP service, convert many
OpenAPI operations, or customize behavior in code. This is a narrow workflow
comparison, not a performance benchmark or a claim that FirstCall replaces
FastMCP, Bruno or Postman.

## Reproduction

On 2026-10-12, `scripts/smoke-native.py` exercised a FirstCall 0.3.1 candidate
against FastMCP 4.1.0 on macOS arm64 with Python 3.12. Both contacted the same
local synthetic HTTP API using a synthetic bearer token. No personal API or
credential was used. The FastMCP API and mapping configuration follow its
[official OpenAPI documentation](https://gofastmcp.com/integrations/openapi).

```sh
python3 -m venv /tmp/firstcall-comparison-env
/tmp/firstcall-comparison-env/bin/pip install fastmcp==4.1.0
/tmp/firstcall-comparison-env/bin/python scripts/smoke-native.py \
  /absolute/path/to/firstcall-cli /tmp/firstcall-comparison --compare-fastmcp
```

Use fresh output directories. `summary.json`, each subprocess's stdout/stderr,
and `openapi.json` record the results. FastMCP is tested through its in-memory
MCP client to the generated tools and real loopback HTTP. FirstCall is tested
through its actual subprocess stdio protocol and real loopback HTTP. These are
not identical client transports, and elapsed setup times are not compared.

## What the exercised setup requires

| Step | FirstCall CLI native workflow | FastMCP OpenAPI workflow |
|---|---|---|
| Runtime | Install the macOS arm64 FirstCall release binary | Create a Python environment and install FastMCP |
| Describe the operation | A recipe plus an explicit tool name, description and input contract | An OpenAPI document with operation IDs, parameters and responses |
| Authenticate | Set the named environment variable; it is omitted from tool arguments | Configure the HTTP client's bearer header from the environment; also omitted from arguments |
| Select the scope | Export one verified operation; package policy pins method, host and path | Add a GET/path `RouteMap` and a catch-all `EXCLUDE` rule to expose one operation |
| Verify and deliver | Run `verify`, then `package-native`; recipient runs the same native binary | Author `FastMCP.from_openapi(...)`, then start the Python server; no prior successful call is required |
| Move the installation | Run `connect --package` from the new binary; it validates and prints current absolute paths | Update the client's Python/script paths and distribute the script, spec and dependencies |

The script's legacy recipe JSON setup is more manual than FirstCall's desktop
curl/OpenAPI workflow. It does not establish that the CLI takes fewer authoring
steps. The concrete benefit demonstrated is a recipient needing no Python or npm
runtime and getting the same admission/redaction policy after relocation.

## Observed results

| Case | FirstCall candidate | FastMCP 4.1.0 configuration tested |
|---|---|---|
| Authenticated lookup | Succeeded three times | Succeeded with both default and restricted route maps |
| Tool scope | One explicit `find_user` tool | Defaults exposed `find_user` and `reset_fixture`; explicit allow-list exposed only `find_user` |
| Authentication input | No bearer argument; required environment name has an empty config placeholder | No bearer argument; HTTP client owns the header |
| Response secret marker | `api_key` value redacted | Returned the synthetic marker; no custom response-redaction hook was added |
| Missing authentication | Rejected before HTTP, with the required environment variable name | HTTP 401 from the fixture, reported as an error with the API's explanation |
| Relocation | New config used the moved package and executable; original files preserved | Python/script paths remain a client deployment concern, not benchmarked here |

FastMCP supports custom mapping and hooks, so this result does not mean it cannot
enforce redaction or stricter policy. Implementing and testing those hooks is
additional application code; the default OpenAPI adapter was the baseline here.
FirstCall's hashes detect changed package files; they are not a signature or proof
that a package author is trustworthy. Read a package's operation before granting
its process credentials, particularly for write tools.

The same installed-binary test separately checks FirstCall's traversal/type/extra
argument rejection, redirect blocking, response size/JSON failures, tampered
packages, and write opt-in. Those are FirstCall regression checks, not claims
about untested FastMCP behavior. FirstCall currently ships this native desktop
release only for Apple Silicon macOS and remains ad-hoc signed, not notarized.
