#!/usr/bin/env python3
"""Live monitor for the FDK pipeline. Serves dashboard/index.html on
http://localhost:7777, plus a JSON aggregate of the current state read
from /tmp/agent-builds/ and .run-logs/*.log. Optionally polls Linear
(team BAP) every 60s when LINEAR_API_KEY is set in env.

Stdlib only. Start with `python3 scripts/monitor.py` or via
`scripts/dashboard.sh` which also opens the browser.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILDS_ROOT = pathlib.Path(os.environ.get("FDK_BUILDS_ROOT", "/tmp/agent-builds"))
LOGS_ROOT = ROOT / ".run-logs"
DASHBOARD_HTML = ROOT / "dashboard" / "index.html"
PORT = int(os.environ.get("FDK_MONITOR_PORT", "7777"))
LINEAR_API_KEY = os.environ.get("LINEAR_API_KEY")
LINEAR_TEAM_KEY = os.environ.get("LINEAR_TEAM_KEY", "BAP")
LINEAR_POLL_SECONDS = 60

_linear_cache: dict = {"tickets": [], "fetchedAt": None, "error": None}
_linear_lock = threading.Lock()


def read_json_safe(path: pathlib.Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def tail_lines(path: pathlib.Path, n: int = 40) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = min(size, 64 * 1024)
            fh.seek(-chunk, 2) if size > chunk else fh.seek(0)
            data = fh.read().decode("utf-8", errors="replace").splitlines()
            return data[-n:]
    except (FileNotFoundError, OSError):
        return []


def latest_log() -> pathlib.Path | None:
    if not LOGS_ROOT.exists():
        return None
    candidates = sorted(LOGS_ROOT.glob("build-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def list_runs() -> list[dict]:
    if not BUILDS_ROOT.exists():
        return []
    runs = []
    for call_dir in sorted(BUILDS_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not call_dir.is_dir():
            continue
        spec = read_json_safe(call_dir / "agent-spec.json") or {}
        coworkers = read_json_safe(call_dir / "coworkers.json") or {}
        mcps = read_json_safe(call_dir / "mcps.json") or {}
        report_path = call_dir / "report.md"
        report_present = report_path.exists()
        agents = []
        for slug, info in (coworkers.get("coworkers") or {}).items() if isinstance(coworkers.get("coworkers"), dict) else []:
            agents.append({
                "slug": slug,
                "status": info.get("status", "unknown"),
                "lastRunId": info.get("lastRunId"),
                "iter": info.get("testIteration"),
            })
        if isinstance(coworkers, list):
            for item in coworkers:
                agents.append({
                    "slug": item.get("slug") or item.get("username"),
                    "status": item.get("status", "unknown"),
                    "lastRunId": item.get("lastRunId"),
                    "iter": item.get("testIteration"),
                })
        if not agents:
            for agent in (spec.get("agents") or []):
                agents.append({
                    "slug": agent.get("slug") or agent.get("agentName"),
                    "status": "planned",
                    "iter": None,
                    "lastRunId": None,
                })
        outputs = []
        for agent in agents:
            slug = agent.get("slug")
            if not slug:
                continue
            tpl = call_dir / slug / "output_template.html"
            if tpl.exists():
                outputs.append({
                    "agent": slug,
                    "previewUrl": f"/preview/{call_dir.name}/{slug}",
                    "sizeKb": round(tpl.stat().st_size / 1024, 1),
                })
        steps = {}
        steps["parse"] = "done" if spec else "pending"
        steps["resolve-tools"] = "done" if (spec.get("agents") or []) and all(a.get("neededTools") is not None for a in spec.get("agents") or []) else ("in-progress" if spec else "pending")
        steps["mcps"] = "bound" if mcps else "pending"
        steps["skills-upload"] = "done" if any(call_dir.joinpath(a.get("slug", "_")).exists() for a in agents if a.get("slug")) else "pending"
        steps["coworkers"] = f"{sum(1 for a in agents if a.get('status') == 'live')}/{len(agents) or 0}"
        steps["report"] = "done" if report_present else "pending"
        runs.append({
            "callId": call_dir.name,
            "prospect": (spec.get("callMeta") or {}).get("prospect"),
            "callDate": (spec.get("callMeta") or {}).get("callDateIso"),
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(call_dir.stat().st_mtime)),
            "agentCount": len(agents),
            "steps": steps,
            "agents": agents,
            "outputs": outputs,
            "reportPresent": report_present,
            "ambiguities": (spec.get("ambiguities") or []),
        })
    return runs


def fetch_linear_loop():
    if not LINEAR_API_KEY:
        with _linear_lock:
            _linear_cache["error"] = "LINEAR_API_KEY not set; Linear panel disabled"
        return
    query = """
    query Dogfooding($key: String!) {
      issues(
        first: 25,
        filter: { team: { key: { eq: $key } }, labels: { name: { eq: "Dogfooding" } } },
        orderBy: updatedAt
      ) {
        nodes {
          identifier title url updatedAt
          state { name type }
          assignee { displayName }
          labels { nodes { name color } }
        }
      }
    }
    """
    payload = {"query": query, "variables": {"key": LINEAR_TEAM_KEY}}
    while True:
        try:
            req = urllib.request.Request(
                "https://api.linear.app/graphql",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": LINEAR_API_KEY},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                nodes = (body.get("data") or {}).get("issues", {}).get("nodes", []) or []
                tickets = [{
                    "identifier": n.get("identifier"),
                    "title": n.get("title"),
                    "url": n.get("url"),
                    "state": (n.get("state") or {}).get("name"),
                    "stateType": (n.get("state") or {}).get("type"),
                    "assignee": (n.get("assignee") or {}).get("displayName"),
                    "labels": [l.get("name") for l in (n.get("labels") or {}).get("nodes", []) or []],
                    "updatedAt": n.get("updatedAt"),
                } for n in nodes]
                with _linear_lock:
                    _linear_cache["tickets"] = tickets
                    _linear_cache["fetchedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _linear_cache["error"] = None
        except Exception as exc:
            with _linear_lock:
                _linear_cache["error"] = f"linear poll failed: {exc.__class__.__name__}: {exc}"
        time.sleep(LINEAR_POLL_SECONDS)


def build_state() -> dict:
    log = latest_log()
    with _linear_lock:
        linear_snapshot = dict(_linear_cache)
    return {
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs": list_runs(),
        "logs": {
            "latestPath": str(log.relative_to(ROOT)) if log else None,
            "tail": tail_lines(log, 60) if log else [],
        },
        "linear": linear_snapshot,
        "config": {
            "buildsRoot": str(BUILDS_ROOT),
            "logsRoot": str(LOGS_ROOT),
            "port": PORT,
            "linearTeamKey": LINEAR_TEAM_KEY,
            "linearEnabled": bool(LINEAR_API_KEY),
        },
    }


SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {format % args}\n")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._serve_file(DASHBOARD_HTML, "text/html; charset=utf-8")
        elif path == "/state.json":
            data = json.dumps(build_state(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/preview/"):
            self._serve_preview(path)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def _serve_file(self, path: pathlib.Path, ctype: str):
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"dashboard html missing")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_preview(self, path: str):
        parts = path.split("/")
        if len(parts) != 4:
            self.send_response(400); self.end_headers(); self.wfile.write(b"bad preview"); return
        _, _, call_id, slug = parts
        if not (SAFE_NAME.match(call_id) and SAFE_NAME.match(slug)):
            self.send_response(400); self.end_headers(); self.wfile.write(b"bad preview name"); return
        target = BUILDS_ROOT / call_id / slug / "output_template.html"
        try:
            resolved = target.resolve()
            if not str(resolved).startswith(str(BUILDS_ROOT.resolve())):
                self.send_response(403); self.end_headers(); self.wfile.write(b"escape attempt"); return
        except OSError:
            self.send_response(404); self.end_headers(); self.wfile.write(b"missing"); return
        self._serve_file(resolved, "text/html; charset=utf-8")


def main():
    if not DASHBOARD_HTML.exists():
        sys.stderr.write(f"warning: {DASHBOARD_HTML} missing; / will 404\n")
    t = threading.Thread(target=fetch_linear_loop, daemon=True)
    t.start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write(f"FDK monitor listening on http://localhost:{PORT}\n")
    sys.stderr.write(f"  builds root: {BUILDS_ROOT}\n")
    sys.stderr.write(f"  logs root:   {LOGS_ROOT}\n")
    sys.stderr.write(f"  linear:      {'enabled' if LINEAR_API_KEY else 'disabled (set LINEAR_API_KEY to enable)'}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nshutting down\n")


if __name__ == "__main__":
    main()
