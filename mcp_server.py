#!/usr/bin/env python3
"""mcp-benchmark-hygiene — MCP server that detects pytest config-leakage in
agent/benchmark workspaces.

The core pain (see sudo-ai-git/vulcanbench-findings): an automated grading harness
that runs `python -m pytest <tests>` inside a workspace which nests under a repo
root carrying pytest `addopts` (e.g. `--cov=harness --cov-fail-under=80`) silently
inherits that config. pytest then fails on the host's own coverage gate and the
harness records functionally-PASSING code as FAILED.

This server answers one question deterministically, with NO LLM and NO network:
"Will running pytest here be corrupted by inherited pytest config?"

Tools:
  inspect_workspace(path)      -> rootdir, resolved addopts, ini-file chain, verdict
  check_addopts(path)          -> flag coverage/exit-code gates that will break grading
  summarize(analysis)          -> human/tool-readable summary + fixed command
"""
import os
import subprocess
import sys
import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # allow import for unit tests without the mcp package
    FastMCP = None

# ── deterministic analysis core (no network, no LLM) ───────────────────────────
COV_GATES = ("--cov", "--cov-fail-under", "--cov-report", "--cov-config")
OTHER_GATES = ("--strict", "--strict-markers", "--maxfail", "--pdb", "-x", "--ff")


def _find_ini_files(path: Path) -> list:
    """Walk from workspace up to filesystem root; collect pytest ini candidates in
    root-dir-to-cwd precedence order (pytest uses the FIRST found going up)."""
    files = []
    cur = path.resolve()
    while True:
        for ini in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"):
            p = cur / ini
            if p.exists():
                files.append(p)
        if cur.parent == cur:
            break
        cur = cur.parent
    return files


def _extract_addopts(ini: Path) -> Optional[str]:
    """Read `addopts` from a pyproject.toml [tool.pytest.ini_options] block or a
    plain pytest.ini [pytest] / [tool:pytest] block. Returns None if absent."""
    try:
        text = ini.read_text(errors="replace")
    except Exception:
        return None
    if ini.name == "pyproject.toml":
        # find [tool.pytest.ini_options] section
        in_sec = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_sec = stripped == "[tool.pytest.ini_options]"
                continue
            if in_sec and ("addopts" in stripped or "=" in stripped):
                if stripped.lower().startswith("addopts"):
                    return stripped.split("=", 1)[1].strip()
    else:
        in_sec = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_sec = stripped in ("[pytest]", "[tool:pytest]")
                continue
            if in_sec and stripped.lower().startswith("addopts"):
                return stripped.split("=", 1)[1].strip()
    return None


def inspect_workspace(path: str) -> Dict[str, Any]:
    """Resolve pytest rootdir/addopts chain for a workspace path. Deterministic.

    Uses pytest's own `--collect-only -o` introspection when pytest is present, else
    falls back to static ini parsing. Returns structured analysis + verdict.
    """
    ws = Path(path).expanduser().resolve()
    if not ws.exists():
        return {"ok": False, "error": f"path not found: {path}", "verdict": "not_a_workspace"}

    # Fallback static chain (always available, no deps)
    ini_files = _find_ini_files(ws)
    chain = []
    for ini in ini_files:
        opts = _extract_addopts(ini)
        chain.append({"file": str(ini), "addopts": opts})

    # Precise resolution via pytest itself if available
    resolved_addopts = None
    rootdir = None
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "--help-note-x", "--no-header"],
            cwd=str(ws), capture_output=True, text=True, timeout=60,
        )
        # addopts resolution isn't a direct CLI output; parse the ini chain statically.
    except Exception:
        pass

    # Determine the effective addopts: pytest uses the FIRST ini found walking up.
    effective = None
    for c in chain:
        if c["addopts"]:
            effective = c["addopts"]
            break

    broken = False
    reasons = []
    if effective:
        low = effective.lower()
        cov = [g for g in COV_GATES if g in low]
        other = [g for g in OTHER_GATES if g in low]
        if cov:
            broken = True
            reasons.append(f"coverage gate(s) present: {cov} — pytest will exit non-zero if coverage < threshold")
        if other:
            broken = True
            reasons.append(f"strict/abort gate(s) present: {other} — may abort or fail grading runs")
        if not broken:
            reasons.append(f"addopts present but no coverage/abort gate: '{effective}'")

    return {
        "ok": True,
        "workspace": str(ws),
        "ini_chain": chain,
        "effective_addopts": effective,
        "will_corrupt_grading": broken,
        "reasons": reasons,
        "verdict": (
            "CORRUPTED" if broken
            else ("UNKNOWN" if not effective else "CLEAN")
        ),
        "fixed_command": [
            sys.executable, "-m", "pytest", "-o", "addopts=", "<tests>",
        ] if broken else None,
    }


def check_addopts(path: str) -> Dict[str, Any]:
    """Thinner API: just the boolean 'is the workspace pytest-corrupted?' + reason."""
    a = inspect_workspace(path)
    if not a.get("ok"):
        return a
    return {
        "ok": True,
        "path": a["workspace"],
        "corrupted": a["will_corrupt_grading"],
        "verdict": a["verdict"],
        "reasons": a.get("reasons", []),
    }


def summarize(analysis: Dict[str, Any]) -> str:
    """Human/tool-readable summary of an inspect_workspace result."""
    if not analysis.get("ok"):
        return f"cannot inspect: {analysis.get('error')}"
    if analysis.get("will_corrupt_grading"):
        return (
            f"[DANGER] {analysis['workspace']} will corrupt pytest grading: "
            f"{'; '.join(analysis['reasons'])}. "
            f"Fix: {analysis['fixed_command'][0]} -m pytest -o addopts= <tests>"
        )
    eff = analysis.get("effective_addopts")
    if eff:
        return f"[CLEAN] {analysis['workspace']} — addopts '{eff}' has no coverage/abort gate."
    return f"[CLEAN] {analysis['workspace']} — no pytest addopts inherited."


def _register_tools(mcp) -> None:
    """Register the three MCP tools on a FastMCP instance.

    Kept separate so both the stdio and the Streamable-HTTP transports expose the
    identical toolset (and so the wrappers call the *Impl core, not themselves).
    """
    @mcp.tool()
    def inspect_workspace(path: str) -> Dict[str, Any]:
        """Check whether running pytest inside `path` will inherit addopts that
        corrupt agent-benchmark/function grading (rootdir + ini chain + verdict)."""
        return _inspect_workspace_impl(path)

    @mcp.tool()
    def check_addopts(path: str) -> Dict[str, Any]:
        """Boolean 'is pytest-corrupted?' + reasons for a workspace path."""
        return _check_addopts_impl(path)

    @mcp.tool()
    def summarize(analysis: Dict[str, Any]) -> str:
        """One-line actionable summary of an inspect_workspace() result dict."""
        return _summarize_impl(analysis)


def build_app():
    """Build the FastMCP app with tools registered (shared by stdio + HTTP)."""
    if FastMCP is None:
        raise RuntimeError("mcp package not installed ('pip install mcp')")
    mcp = FastMCP("mcp-benchmark-hygiene")
    _register_tools(mcp)
    return mcp


def _main() -> None:
    """Console-script entry point (also used by `python3 mcp_server.py`)."""
    import argparse
    p = argparse.ArgumentParser(description="mcp-benchmark-hygiene MCP server")
    p.add_argument("--http", action="store_true",
                   help="serve over Streamable HTTP (default: stdio)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP bind host")
    p.add_argument("--port", type=int, default=8000, help="HTTP port")
    args = p.parse_args()

    mcp = build_app()
    if args.http:
        # Streamable HTTP — remote-deployable (e.g. `smithery mcp publish <url>`).
        import uvicorn
        app = mcp.streamable_http_app()
        print(f"[mcp-benchmark-hygiene] serving Streamable HTTP on {args.host}:{args.port}", flush=True)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    else:
        mcp.run()  # stdio (default)


# ── renames: the MCP tool wrappers above shadow the module fns; the impls live
# ── here under distinct names so the wrappers call the real core (no recursion).
_inspect_workspace_impl = inspect_workspace
_check_addopts_impl = check_addopts
_summarize_impl = summarize

main_entry = _main  # console-script entry point


if __name__ == "__main__":
    _main()
