# mcp-benchmark-hygiene

**Deterministic detection of pytest config-leakage that silently corrupts
agent-benchmark / function grading.**

No LLM. No network. One question, answered reliably:

> *If I run `python -m pytest <tests>` inside this workspace, will it inherit a
> host coverage/abort gate that mis-scores passing code as failed?*

---

## The bug this catches

Automated agent-evaluation harnesses often run `python -m pytest <hidden_tests>`
inside the target's workspace. If that workspace nests under a repo root carrying
pytest `addopts` — e.g.:

```toml
[tool.pytest.ini_options]
addopts = "--cov=harness --cov-report=term-missing:skip-covered --cov-fail-under=80"
```

...pytest resolves that host `pyproject.toml` as its rootdir, inherits the
`addopts`, and fails on **the host's own coverage gate** (`harness` collected at
0% → below threshold → non-zero exit). The harness then records functionally
PASSING code as FAILED.

This is exactly the bug documented in
**[sudo-ai-git/vulcanbench-findings](https://github.com/sudo-ai-git/vulcanbench-findings)**:
VulcanBench's declarative grader mis-scored every functional task as `0.0` for
this reason; with `-o addopts=` neutralizing the leak, the same workspaces passed
10/10.

## The fix it hands you

When a workspace is flagged `CORRUPTED`, the tool returns the corrected command:

```bash
python -m pytest -o addopts= <tests>
```

`-o addopts=` strips inherited coverage/abort gates. (Or run the grader from
outside the repo root.)

## Tools

| tool | purpose |
|---|---|
| `inspect_workspace(path)` | full analysis: ini chain, effective addopts, CLEAN/CORRUPTED/UNKNOWN verdict + corrected command |
| `check_addopts(path)` | thin boolean: `corrupted` + reasons |
| `summarize(analysis)` | one-line actionable summary string |

## Deterministic core (no deps)

The analysis walks the workspace directory **up to filesystem root**, reading
`pyproject.toml` / `pytest.ini` / `tox.ini` / `setup.cfg` in pytest's
first-found order, and extracts `addopts`. Flags:

- **coverage gates** — `--cov`, `--cov-fail-under`, `--cov-report`, `--cov-config`
- **abort/strict gates** — `--maxfail`, `-x`, `--strict`, `--strict-markers`, `--pdb`, `--ff`

Only gates that change exit codes / abort grading are flagged. A harmless
`addopts` is reported `CLEAN` with the exact string.

## Install & run (MCP stdio)

```json
{ "mcpServers": {
    "benchmark-hygiene": { "command": "python3", "args": ["/abs/path/to/mcp_server.py"] }
}}
```

Requires the official `mcp` python package (`pip install mcp`). The deterministic
core (`inspect_workspace` / `check_addopts` / `summarize`) imports and runs with
**zero** dependencies — the `mcp` package is only needed for the stdio server.

### Streamable HTTP (remote/Smithery-publishable)

```bash
python3 mcp_server.py --http --port 8137   # serves on http://<host>:8137/mcp/
```

Run with `--http` to serve over Streamable HTTP (a remote MCP endpoint) instead of
stdio. This is the transport `smithery mcp publish <url>` expects for URL-based
publishing — so once a Smithery service token exists, the server deploys as-is.

## Example

```
inspect_workspace(path="/home/runner/vulcanbench/workspace/task-1")
→ {
    "ok": true,
    "workspace": "/home/runner/vulcanbench/workspace/task-1",
    "ini_chain": [{"file": "/home/runner/vulcanbench/pyproject.toml",
                   "addopts": "--cov=harness ... --cov-fail-under=80"}],
    "effective_addopts": "--cov=harness ... --cov-fail-under=80",
    "will_corrupt_grading": true,
    "verdict": "CORRUPTED",
    "fixed_command": ["python3", "-m", "pytest", "-o", "addopts=", "<tests>"],
    "reasons": ["coverage gate(s) present: ['--cov', '--cov-fail-under']"]
}
```

## Verification

- `python3 test_detector.py` — 5/5 core detection checks (root gate, nested
  inheritance, clean, abort gate, pyproject-no-pytest)
- `python3 test_e2e.py` — drives the real MCP stdio transport (initialize →
  tools/call) and asserts CORRUPTED / CLEAN thread through the wire

## License & provenance

MIT. Independently derived from the documented VulcanBench #79 finding; no
endorsement by or affiliation with morganlinton/VulcanBench implied.
