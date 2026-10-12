# FirstCall CLI usage

`firstcall-cli` is the automation surface for agents, CI, and local scripts. It owns recipe verification, package export, package validation and inspection, package import, local recipe summaries, and JSON reports.

CLI verification is environment-first. It does not read GUI keyring or session-memory secrets.

## Run an exported MCP tool

The desktop app exports a native MCP package after request verification and tool
description. Copy its client-config.json server entry into your MCP client. It
runs the release executable directly:

```sh
/path/to/firstcall-cli serve --package /absolute/path/to/exported-tool
```

The process speaks MCP over stdin/stdout; it is intended to be started by an MCP
client. No Node.js, npm installation, or build is needed. Authentication comes
from the environment of that process. The exported configuration lists the
required names with empty values for you to supply in your client's settings.
Do not put credential values in the package files.

Methods other than GET and HEAD require an explicit `--allow-mutating` runtime option. The GUI
adds that option only after you enable write requests for the exported tool.
Without it, the native server rejects write operations.

The runtime validates the package manifest, tool input contract, and endpoint
policy, then makes the real request when a tool is called. It returns structured
redacted data and reports transport, HTTP, input, and size-limit failures. It
does not modify recipe storage while serving a package.

## Command Overview

```text
firstcall-cli version
firstcall-cli serve --package PATH [--allow-mutating]
firstcall-cli connect --package PATH [--allow-mutating]
firstcall-cli package-native --recipe-json PATH --tool-json PATH --out DIR [--allow-mutating]
firstcall-cli explain --recipe-json PATH
firstcall-cli package --recipe-json PATH --out DIR
firstcall-cli package --recipe-id ID --out DIR [--data-dir PATH --config-dir PATH]
firstcall-cli verify --recipe-json PATH [--out PATH] [--lock-out PATH] [--allow-mutating] [--json]
firstcall-cli verify --recipe-json PATH [--allow-mutating] [--dry-run|--preflight] [--json]
firstcall-cli verify --recipe-id ID [--data-dir PATH --config-dir PATH] [--allow-mutating] [--json]
firstcall-cli verify --recipe-id ID [--data-dir PATH --config-dir PATH] [--allow-mutating] [--dry-run|--preflight] [--json]
firstcall-cli validate-package --dir PATH [--json] [--mcp-compile-smoke]
firstcall-cli inspect-package --dir PATH [--json]
firstcall-cli import-package --dir PATH [--data-dir PATH --config-dir PATH] [--json]
firstcall-cli recipe-list [--data-dir PATH --config-dir PATH] [--json]
firstcall-cli recipe-show --id ID [--data-dir PATH --config-dir PATH] [--json]
```

Without `--json`, commands keep human-readable output. With `--json`, report-producing commands emit machine-readable JSON for agents, CI, and scripts. JSON reports are safe summaries and do not include raw request/response bodies, headers, environment values, slot current values, or resolved secret-bearing URLs.

## Recipe Verification

Verify a recipe JSON from the local machine:

```powershell
$env:FIRSTCALL_BEARER_TOKEN = "..."
firstcall-cli verify `
  --recipe-json ./recipe.json `
  --out ./recipe.verified.json `
  --lock-out ./verified.lock.json
```

Actual verification executes HTTP. Secrets must come from environment variables, and raw secret values are not written to the updated recipe, lock file, human output, or JSON report. `POST`, `PUT`, `PATCH`, and `DELETE` require `--allow-mutating`.

Check readiness without sending HTTP:

```powershell
firstcall-cli verify --recipe-json ./recipe.json --dry-run --json
```

`verify --dry-run` and `verify --preflight` are aliases. They perform local static/runtime-input preflight only, do not execute HTTP, and do not write `--out` or `--lock-out` files. Reports list required environment variables by name with `set` or `missing` status only, never values.

Verify or preflight a stored recipe:

```powershell
firstcall-cli verify --recipe-id 1 --dry-run --json
firstcall-cli verify --recipe-id 1 --allow-mutating --json
```

Actual `verify --recipe-id` reads from local recipe storage and updates local SQLite verification metadata only on success. It does not support `--out` or `--lock-out`.

## Advanced TypeScript package export

These CLI package commands preserve the existing TypeScript export format. For
a native package that runs directly, use the desktop MCP export described above.

Package a verified recipe JSON:

```powershell
firstcall-cli package --recipe-json ./recipe.verified.json --out ./dist/my-agent-tool
```

Package a verified recipe from local recipe storage:

```powershell
firstcall-cli package --recipe-id 1 --out ./dist/my-agent-tool
```

`package --recipe-id` reads the stored recipe payload from local SQLite storage. It does not execute HTTP, does not mutate SQLite, and requires successful local verification metadata before export.

The generated package includes:

- `recipe.yaml`
- `skill.md`
- `policy.json`
- `verified.lock.json`
- `package.manifest.json`
- `mcp-server/` with a TypeScript MCP server template

Raw secrets are never exported. Secret values are represented as environment variable references such as `FIRSTCALL_BEARER_TOKEN` or `FIRSTCALL_API_KEY`.

Generated `mcp-server/` files are template artifacts. They are not source of truth for package import. Static package validation does not install Node dependencies or execute generated MCP code; generated MCP execution needs a separate runtime check.

## Validate, Inspect, And Import

Create a local sample package:

```powershell
firstcall-cli package --recipe-json fixtures/verified-agent-recipe.json --out ./dist/sample-agent-tool
```

Run static validation:

```powershell
firstcall-cli validate-package --dir ./dist/sample-agent-tool --json
```

`validate-package` checks package structure, schema metadata, lock metadata, policy shape, MCP template markers, obvious secret leaks, and manifest hashes when present. It does not execute HTTP, run npm, compile TypeScript, run Node, run MCP Inspector, execute the generated MCP server, import recipes, or modify files.

Maintainers with local Node dependencies already installed can request optional compile smoke:

```powershell
firstcall-cli validate-package --dir ./dist/sample-agent-tool --mcp-compile-smoke
```

`--mcp-compile-smoke` uses local `mcp-server/node_modules` when present. It does not run `npm install`, use `npx`, run MCP Inspector, execute the generated server, send HTTP, or read secrets. Missing `node_modules` is reported as a warning.

Inspect import-readiness:

```powershell
firstcall-cli inspect-package --dir ./dist/sample-agent-tool --json
```

`inspect-package` runs validation and checks import-readiness conditions such as manifest presence, recipe/policy agreement, and verified lock metadata. It does not import recipes, modify files, modify app storage, execute HTTP, or use generated `mcp-server/` files as source of truth.

Import an inspect-ready package:

```powershell
firstcall-cli import-package --dir ./dist/sample-agent-tool --json
```

`import-package` writes one recipe into local SQLite storage and marks it as requiring local re-verification. It does not preserve verified status, import raw secrets, execute HTTP, run npm, compile TypeScript, run Node, run MCP Inspector, or execute generated MCP runtime.

## Local Recipe Storage

List stored recipes:

```powershell
firstcall-cli recipe-list --json
```

Show one stored recipe:

```powershell
firstcall-cli recipe-show --id 1 --json
```

For controlled tests, storage can be overridden with both directories:

```powershell
firstcall-cli recipe-list --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --json
```

`recipe-list` and `recipe-show` are read-only safe summary commands. Output does not include `RuntimeSlot.current_value`, raw secrets, environment values, resolved secret-bearing URLs, or body contents.

## Full Local-First Lifecycle

```powershell
firstcall-cli package --recipe-json ./recipe.verified.json --out ./dist/sample-agent-tool
firstcall-cli validate-package --dir ./dist/sample-agent-tool --json
firstcall-cli inspect-package --dir ./dist/sample-agent-tool --json
firstcall-cli import-package --dir ./dist/sample-agent-tool --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --json
firstcall-cli recipe-list --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --json
firstcall-cli recipe-show --id 1 --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --json
firstcall-cli verify --recipe-id 1 --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --dry-run --json
firstcall-cli verify --recipe-id 1 --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --allow-mutating
firstcall-cli package --recipe-id 1 --data-dir ./tmp/firstcall-data --config-dir ./tmp/firstcall-config --out ./dist/reverified-agent-tool
firstcall-cli validate-package --dir ./dist/reverified-agent-tool --json
firstcall-cli inspect-package --dir ./dist/reverified-agent-tool --json
```

Imported recipes require local re-verification before `package --recipe-id` can export them. `verify --recipe-id --dry-run` does not execute HTTP or update SQLite. Actual `verify --recipe-id` updates SQLite verification metadata only on success. `package --recipe-id` does not execute HTTP or mutate SQLite.

## Native export and relocation (0.3.1)

`package` retains the legacy generated TypeScript package format. `package-native`
uses the same native exporter as the desktop app, requires a verified recipe and
an explicit `tool.json` contract, and prints the client configuration as JSON.
It stages the package atomically and refuses to overwrite an existing directory.
Tool definitions must describe all non-secret input slots with no extra fields;
see `scripts/smoke-native.py` for a complete synthetic example.

```sh
firstcall-cli verify --recipe-json recipe.json --out verified.json
firstcall-cli package-native --recipe-json verified.json --tool-json tool.json --out /absolute/new/tool
firstcall-cli connect --package /absolute/moved/tool
```

`connect` uses the running executable's canonical path and the supplied package's
canonical directory. It performs the same admission checks as `serve`, including
manifest hashes, tool contract, method, host and path policy. Invalid or tampered
packages produce no configuration on stdout. The command does not send HTTP,
read environment credential values, edit the exported configuration, or modify
recipe storage. Repeated calls return the same configuration at the same paths.
Credential names are included with empty values; supply them in the client's
settings after replacing its server entry. Do not redirect output over an
existing package file: the shell can truncate a file before validation starts.

For non-GET/HEAD tools, verification, native export, refreshed connection and
serving each require `--allow-mutating`. Moving files never grants this opt-in.
The flag is an explicit acknowledgment, not an authorization system for an API.

To reproduce the installed-binary loopback checks with only Python's standard
library (the output directory must be new):

```sh
python3 scripts/smoke-native.py /absolute/path/to/firstcall-cli /tmp/firstcall-evidence
```

The test covers actual verify/export/serve, redaction, three repeated reads,
relocation, missing credentials, invalid arguments, redirects, oversized and
malformed responses, package tampering, and write opt-in at each stage. Closing
an idle server preserves package files; cancelling a process cannot undo an HTTP
request already sent or a remote mutation already committed.

## Optional query and header values

Verification omits an optional query/header field when a declared optional input
used by that field is unset or blank. It omits the whole field, including a
composed template; literal fields and supplied values are retained. A required
field, required input or undeclared placeholder is never silently dropped.
The verified recipe retains its optional contract so later MCP callers can
supply the value or omit it. MCP arguments are never silently populated from
matching environment variables.

Run `python3 scripts/smoke-optional.py /path/to/firstcall-cli /new/evidence` for
real verify → native export → stdio MCP → HTTP checks of both omissions and
supplied values. These checks use a local synthetic server and no credentials.
