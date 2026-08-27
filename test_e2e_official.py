#!/usr/bin/env python3
"""E2E over the real MCP stdio transport using the OFFICIAL mcp client package.

This is the same client the earlier mcp-skill-sec / mcp-verify-claim assets were
E2E-verified with, and it correctly frames the MCP handshake (my hand-rolled
subprocess JSON-RPC in test_e2e.py does not satisfy FastMCP's initialization).
"""
import asyncio, json, os, sys, tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)

async def main():
    tmp = tempfile.mkdtemp()
    write(os.path.join(tmp, "pyproject.toml"),
          '[tool.pytest.ini_options]\naddopts = "--cov=harness --cov-fail-under=80"\n')
    write(os.path.join(tmp, "sub", "test_x.py"), "def test_x():\n    assert True\n")
    clean = tempfile.mkdtemp()
    write(os.path.join(clean, "test_y.py"), "def test_y():\n    assert 1==1\n")

    srv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    params = StdioServerParameters(command=sys.executable, args=[srv], env=dict(os.environ))
    results = []
    async with stdio_client(params) as (read, write_):
        async with ClientSession(read, write_) as session:
            await session.initialize()
            corr_path = os.path.join(tmp, "sub")
            res = await session.call_tool("inspect_workspace", {"path": corr_path})
            text = res.content[0].text
            verdict = json.loads(text).get("verdict")
            results.append(("nested corrupt -> CORRUPTED", verdict == "CORRUPTED"))
            print(f"[{'PASS' if verdict=='CORRUPTED' else 'FAIL'}] nested workspace verdict = {verdict}")

            res = await session.call_tool("check_addopts", {"path": clean})
            text = res.content[0].text
            corrupted = json.loads(text).get("corrupted")
            results.append(("clean workspace not corrupted", corrupted is False))
            print(f"[{'PASS' if corrupted is False else 'FAIL'}] clean workspace corrupted = {corrupted}")

            res = await session.call_tool("summarize",
                                          {"analysis": json.loads((await session.call_tool(
                                              "inspect_workspace", {"path": corr_path})).content[0].text)})
            summ = res.content[0].text
            has_fix = "-o addopts=" in summ
            results.append(("summary includes fix", has_fix))
            print(f"[{'PASS' if has_fix else 'FAIL'}] summary includes corrected command: {summ[:90]}")

    ok = all(r[1] for r in results)
    print("\nOFFICIAL-MCP-CLIENT E2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
