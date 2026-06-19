#!/usr/bin/env python3
"""Minimal starter for a HeyBap mini-app panel.

Usage:
    python render_panel.py <live_url>

Writes /app/output.html as a self-contained HTML page that:
  1. Reads the initial snapshot from <live_url>/state on load.
  2. Opens an SSE stream to <live_url>/stream for live deltas.
  3. Posts user actions to <live_url>/action.

Adapt the rendering (init / applyDelta / button handlers) to your domain.
"""
import sys
import os
import html
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_PATH = Path(os.environ.get("HEYBAP_OUTPUT_PATH", "/app/output.html"))

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0a0e16; --bg-elev: #0f1420; --bg-card: #161c2c;
    --border: #2a334a; --text: #f0f4fa; --text-muted: #a3aec5;
    --accent: #6ea1ff; --danger: #f87171; --success: #34d399;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif;
    font-size: 14px; line-height: 1.55;
  }
  body { display: flex; flex-direction: column; overflow: hidden; }
  header { padding: 12px 16px; background: var(--bg-elev); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  .pill { padding: 4px 10px; border-radius: 999px; background: var(--bg-card);
    border: 1px solid var(--border); font-size: 12px; }
  .pill .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--text-muted); margin-right: 6px; vertical-align: middle; }
  .pill.live .dot { background: var(--danger); }
  main { flex: 1; overflow-y: auto; padding: 16px; }
  .card { background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px; margin-bottom: 12px; }
  .card h3 { margin: 0 0 8px 0; font-size: 16px; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  button { padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg-elev); color: var(--text); cursor: pointer; font-size: 13px; }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); color: #0a0e16; border-color: var(--accent); }
  .empty { color: var(--text-muted); text-align: center; padding: 40px 16px; }
</style>
</head>
<body>
  <header>
    <span class="pill live" id="status"><span class="dot"></span><span id="status-text">Connecting…</span></span>
    <span style="flex:1"></span>
    <span class="pill" id="counter">0 items</span>
  </header>
  <main id="main"><div class="empty">Loading…</div></main>

<script>
  const API_BASE = "__API_BASE__";
  const SESSION_ID = "__SESSION_ID__";

  const $main = document.getElementById("main");
  const $status = document.getElementById("status-text");
  const $counter = document.getElementById("counter");

  const state = { items: [] };

  function render() {
    if (state.items.length === 0) {
      $main.innerHTML = '<div class="empty">No items yet.</div>';
    } else {
      $main.innerHTML = state.items.map(item => `
        <div class="card" data-id="${item.id}">
          <h3>${escapeHtml(item.title)}</h3>
          <div>${escapeHtml(item.body || "")}</div>
          <div class="actions">
            <button class="primary" data-action="approve" data-id="${item.id}">Approve</button>
            <button data-action="reject" data-id="${item.id}">Reject</button>
          </div>
        </div>
      `).join("");
    }
    $counter.textContent = `${state.items.length} items`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  async function loadInitialSnapshot() {
    try {
      const r = await fetch(`${API_BASE}/api/sessions/${SESSION_ID}/state`);
      if (!r.ok) throw new Error(`state ${r.status}`);
      const data = await r.json();
      state.items = data.items || [];
      render();
    } catch (e) {
      $main.innerHTML = `<div class="empty">Failed to load: ${escapeHtml(e.message)}</div>`;
    }
  }

  function openStream() {
    const es = new EventSource(`${API_BASE}/api/sessions/${SESSION_ID}/stream`);
    es.addEventListener("message", e => {
      try { applyDelta(JSON.parse(e.data)); } catch {}
    });
    es.addEventListener("error", () => {
      $status.textContent = "Reconnecting…";
      setTimeout(() => { $status.textContent = "Live"; }, 1500);
    });
    es.addEventListener("open", () => { $status.textContent = "Live"; });
  }

  function applyDelta(ev) {
    if (ev.type === "item_added") {
      state.items.push(ev.item);
    } else if (ev.type === "item_removed") {
      state.items = state.items.filter(i => i.id !== ev.id);
    } else if (ev.type === "item_updated") {
      const idx = state.items.findIndex(i => i.id === ev.item.id);
      if (idx !== -1) state.items[idx] = ev.item;
    }
    render();
  }

  $main.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const itemId = btn.dataset.id;
    btn.disabled = true;
    try {
      const r = await fetch(`${API_BASE}/api/sessions/${SESSION_ID}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, item_id: itemId, idempotency_key: crypto.randomUUID() }),
      });
      if (!r.ok) throw new Error(`action ${r.status}`);
      // Don't optimistically update — wait for the SSE delta to drive the DOM.
    } catch (e) {
      console.error(e);
      btn.disabled = false;
    }
  });

  loadInitialSnapshot();
  openStream();
</script>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: render_panel.py <live_url>", file=sys.stderr)
        sys.exit(1)

    live_url = sys.argv[1].rstrip("/")
    parsed = urlparse(live_url)
    api_base = f"{parsed.scheme}://{parsed.netloc}"
    session_id = parsed.path.rstrip("/").split("/")[-1]

    output = (
        TEMPLATE
        .replace("__TITLE__", html.escape("Bap mini-app"))
        .replace("__API_BASE__", api_base)
        .replace("__SESSION_ID__", session_id)
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(output)} bytes, session={session_id})")


if __name__ == "__main__":
    main()
