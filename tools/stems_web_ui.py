#!/usr/bin/env python3
from __future__ import annotations

import cgi
import html
import json
import subprocess
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stems_injector_core import build_sidecar, report_to_json

HOST = "127.0.0.1"
PORT = 8765
APP_VERSION = "web-ui-2026-02-10c"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / ".web_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Serato Stems Builder</title>
<style>
  :root {
    --bg:#10131d; --panel:#181d2b; --line:#2b3348; --text:#f4f7ff; --muted:#b8c3dc; --accent:#4da3ff;
    --ok:#89f0b3; --err:#ff9aa9;
  }
  body { margin:0; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; background:linear-gradient(135deg,#0d1119,#141a29); color:var(--text); }
  .wrap { max-width:1040px; margin:0 auto; padding:24px; }
  h1 { margin:0 0 8px; font-size:28px; }
  .sub { color:var(--muted); margin:0 0 16px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin:12px 0; }
  .row { display:grid; grid-template-columns:260px 1fr auto; gap:10px; align-items:center; margin:8px 0; }
  label { font-weight:600; }
  input[type=text] { width:100%; box-sizing:border-box; padding:10px; border-radius:8px; border:1px solid #3a445f; background:#0f1420; color:var(--text); }
  .mode { display:flex; gap:16px; flex-wrap:wrap; align-items:center; }
  .btn { background:var(--accent); border:none; color:white; font-weight:700; padding:10px 14px; border-radius:9px; cursor:pointer; }
  .btn.secondary { background:#404b68; }
  .hint { color:var(--muted); font-size:13px; }
  pre { background:#0f1420; border:1px solid #3a445f; border-radius:8px; padding:12px; overflow:auto; white-space:pre-wrap; }
  .ok { color:var(--ok); }
  .err { color:var(--err); }
  .drop { border:1px dashed #5b6b96; border-radius:8px; padding:7px 10px; color:var(--muted); font-size:12px; }
  .drop.over { border-color:var(--accent); color:var(--text); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Serato Stems Builder</h1>

  <form method="post" action="/build">
    <div class="card">
      <div class="mode">
        <label><input type="radio" name="mode" value="four" {mode_four_checked}> 4 stems (vocals, bass, drums, melody)</label>
        <label><input type="radio" name="mode" value="two" {mode_two_checked}> 2 stems (vocals + instrumental)</label>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <label>Base audio file</label>
        <input id="base" type="text" name="base" value="{base}" placeholder="Path auto-filled by Browse/Drop or paste absolute path" required />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('base','audio')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('base')">Upload Browse</button>
        </div>
      </div>
      <div class="drop" data-target="base">Drop base audio file here</div>

      <div class="row">
        <label>Vocals MP3</label>
        <input id="vocals" type="text" name="vocals" value="{vocals}" placeholder="Path auto-filled by Browse/Drop" required />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('vocals','mp3')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('vocals')">Upload Browse</button>
        </div>
      </div>
      <div class="drop" data-target="vocals">Drop vocals file here</div>

      <div class="row mode-four-only">
        <label>Bass MP3 (4-stem)</label>
        <input id="bass" type="text" name="bass" value="{bass}" placeholder="Path auto-filled by Browse/Drop" />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('bass','mp3')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('bass')">Upload Browse</button>
        </div>
      </div>
      <div class="drop mode-four-only" data-target="bass">Drop bass file here</div>

      <div class="row mode-four-only">
        <label>Drums MP3 (4-stem)</label>
        <input id="drums" type="text" name="drums" value="{drums}" placeholder="Path auto-filled by Browse/Drop" />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('drums','mp3')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('drums')">Upload Browse</button>
        </div>
      </div>
      <div class="drop mode-four-only" data-target="drums">Drop drums file here</div>

      <div class="row mode-four-only">
        <label>Melody MP3 (4-stem)</label>
        <input id="melody" type="text" name="melody" value="{melody}" placeholder="Path auto-filled by Browse/Drop" />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('melody','mp3')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('melody')">Upload Browse</button>
        </div>
      </div>
      <div class="drop mode-four-only" data-target="melody">Drop melody file here</div>

      <div class="row mode-two-only">
        <label>Instrumental MP3 (2-stem)</label>
        <input id="instrumental" type="text" name="instrumental" value="{instrumental}" placeholder="Path auto-filled by Browse/Drop" />
        <div style="display:flex; gap:8px;">
          <button class="btn secondary" type="button" onclick="pickLocal('instrumental','mp3')">Local Browse</button>
          <button class="btn secondary" type="button" onclick="pickUpload('instrumental')">Upload Browse</button>
        </div>
      </div>
      <div class="drop mode-two-only" data-target="instrumental">Drop instrumental file here</div>

      <input type="hidden" name="two_stem_strategy" value="mute" />

      <input id="copy_to" type="hidden" name="copy_to" value="{copy_to}" />
      <button class="btn" type="submit">Build Stem File</button>
    </div>
  </form>

  <div style="display:none;">{result}</div>
</div>

<script>
const pickers = {};

function makeHiddenPicker(id) {
  const input = document.createElement('input');
  input.type = 'file';
  input.style.display = 'none';
  input.addEventListener('change', async () => {
    if (!input.files || !input.files.length) return;
    await uploadToField(id, input.files[0]);
    input.value = '';
  });
  document.body.appendChild(input);
  pickers[id] = input;
}

async function uploadToField(fieldId, file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/upload_temp', { method: 'POST', body: fd });
  const data = await r.json();
  if (!r.ok) {
    alert('Upload failed: ' + (data.error || r.status));
    return;
  }
  const el = document.getElementById(fieldId);
  el.value = data.path;
}

function pickUpload(id) {
  if (!pickers[id]) makeHiddenPicker(id);
  pickers[id].click();
}

async function pickLocal(id, kind) {
  const r = await fetch('/pick_local?kind=' + encodeURIComponent(kind || 'any'));
  const data = await r.json();
  if (!r.ok) {
    alert('Local picker failed: ' + (data.error || r.status));
    return;
  }
  if (data.path) document.getElementById(id).value = data.path;
}

function setupDrop() {
  document.querySelectorAll('.drop').forEach(zone => {
    const target = zone.getAttribute('data-target');
    const prevent = e => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter','dragover','dragleave','drop'].forEach(ev => zone.addEventListener(ev, prevent));
    zone.addEventListener('dragenter', () => zone.classList.add('over'));
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', async (e) => {
      zone.classList.remove('over');
      const uri = e.dataTransfer ? (e.dataTransfer.getData('text/uri-list') || '') : '';
      if (uri) {
        const first = uri.split('\\n').map(s => s.trim()).find(s => s && !s.startsWith('#'));
        if (first && first.startsWith('file://')) {
          document.getElementById(target).value = decodeURIComponent(first.replace('file://', ''));
          return;
        }
      }
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) {
        await uploadToField(target, files[0]);
        return;
      }
      const txt = e.dataTransfer ? (e.dataTransfer.getData('text/plain') || '') : '';
      if (txt) {
        document.getElementById(target).value = txt.replace(/^file:\/\//, '');
      }
    });
  });
}

function applyModeVisibility() {
  const selected = (document.querySelector('input[name="mode"]:checked') || {}).value || 'four';
  const isTwo = selected === 'two';

  document.querySelectorAll('.mode-two-only').forEach(el => {
    el.style.display = isTwo ? '' : 'none';
  });
  document.querySelectorAll('.mode-four-only').forEach(el => {
    el.style.display = isTwo ? 'none' : '';
  });

  const instrumental = document.getElementById('instrumental');
  const bass = document.getElementById('bass');
  const drums = document.getElementById('drums');
  const melody = document.getElementById('melody');
  if (instrumental) instrumental.required = isTwo;
  if (bass) bass.required = !isTwo;
  if (drums) drums.required = !isTwo;
  if (melody) melody.required = !isTwo;
}

document.querySelectorAll('input[name="mode"]').forEach(r => {
  r.addEventListener('change', applyModeVisibility);
});

setupDrop();
applyModeVisibility();
</script>
</body>
</html>
"""


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def result_block(ok: bool, text: str) -> str:
    cls = "ok" if ok else "err"
    title = "Success" if ok else "Error"
    return f'<div class="card"><h3 class="{cls}">{title}</h3><pre>{html.escape(text)}</pre></div>'


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/pick_local":
            qs = parse_qs(parsed.query, keep_blank_values=True)
            kind = (qs.get("kind", ["any"])[0] or "any").lower()
            self._pick_local(kind)
            return
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        self._send_page({})

    def do_POST(self):
        if self.path == "/upload_temp":
            self._upload_temp()
            return
        if self.path == "/build":
            self._build()
            return
        self.send_error(404)

    def _upload_temp(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            },
        )
        field = form["file"] if "file" in form else None
        if field is None or not getattr(field, "filename", None):
            json_response(self, 400, {"error": "No file uploaded"})
            return

        original = Path(field.filename).name
        safe_name = f"{uuid.uuid4().hex}_{original}"
        target = UPLOAD_DIR / safe_name
        data = field.file.read()
        target.write_bytes(data)
        json_response(self, 200, {"path": str(target)})

    def _pick_local(self, kind: str):
        if kind == "audio":
            prompt = "Select base audio file"
        elif kind == "mp3":
            prompt = "Select MP3 stem file"
        else:
            prompt = "Select file"
        prompt_escaped = prompt.replace('"', '\\"')
        try:
            p = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'set f to choose file with prompt "{prompt_escaped}"',
                    "-e",
                    "POSIX path of f",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            path = p.stdout.strip()
            json_response(self, 200, {"path": path})
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or "Picker cancelled or failed").strip()
            json_response(self, 400, {"error": msg})

    def _build(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

        mode = form.get("mode", "four")
        try:
            base = Path(form.get("base", "").strip())
            vocals = Path(form.get("vocals", "").strip())
            bass = Path(form.get("bass", "").strip()) if form.get("bass", "").strip() else None
            drums = Path(form.get("drums", "").strip()) if form.get("drums", "").strip() else None
            melody = Path(form.get("melody", "").strip()) if form.get("melody", "").strip() else None
            instrumental = Path(form.get("instrumental", "").strip()) if form.get("instrumental", "").strip() else None

            # Prevent writing next to temp uploaded base copy by mistake.
            if UPLOAD_DIR in base.parents:
                raise ValueError(
                    "Base audio path is in .web_uploads temp storage. Use Local Browse for the real library audio path."
                )

            two_stem_strategy = (form.get("two_stem_strategy", "mute") or "mute").strip().lower()
            if two_stem_strategy not in ("compat", "mute"):
                two_stem_strategy = "mute"

            if mode == "two":
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=None,
                    drums=None,
                    melody=None,
                    instrumental=instrumental,
                    two_stem_strategy="mute",
                    overwrite=True,
                )
            else:
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=bass,
                    drums=drums,
                    melody=melody,
                    instrumental=None,
                    two_stem_strategy="compat",
                    overwrite=True,
                )

            copy_to = form.get("copy_to", "").strip()
            if copy_to:
                out = Path(report["output_sidecar"])
                target = Path(copy_to)
                if target.exists() and target.is_dir():
                    dest = target / out.name
                elif str(target).endswith(".serato-stems"):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    dest = target
                else:
                    target.mkdir(parents=True, exist_ok=True)
                    dest = target / out.name
                dest.write_bytes(out.read_bytes())
                report["copied_to"] = str(dest)

            form["result"] = result_block(True, report_to_json(report))
            self._send_page(form)
        except Exception as e:
            detail = f"{e}\\n\\n{traceback.format_exc()}"
            form["result"] = result_block(False, detail)
            self._send_page(form)

    def _send_page(self, form: dict):
        mode = form.get("mode", "four")
        strat = (form.get("two_stem_strategy", "mute") or "mute").strip().lower()
        tokens = {
            "app_version": APP_VERSION,
            "mode_four_checked": "checked" if mode == "four" else "",
            "mode_two_checked": "checked" if mode == "two" else "",
            "two_stem_compat_selected": "selected" if strat != "mute" else "",
            "two_stem_mute_selected": "selected" if strat == "mute" else "",
            "base": esc(form.get("base", "")),
            "vocals": esc(form.get("vocals", "")),
            "bass": esc(form.get("bass", "")),
            "drums": esc(form.get("drums", "")),
            "melody": esc(form.get("melody", "")),
            "instrumental": esc(form.get("instrumental", "")),
            "copy_to": esc(form.get("copy_to", "")),
            "result": form.get("result", ""),
        }
        html_text = PAGE
        for key, value in tokens.items():
            html_text = html_text.replace("{" + key + "}", value)
        data = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args):
        return


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Serato Stems Web UI: http://{HOST}:{PORT} ({APP_VERSION})")
    print(f"Temp upload dir: {UPLOAD_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
