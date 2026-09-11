"""Local web UI for stockgen v2 — drag&drop, before/after preview, CSV export.

Zero extra deps: stdlib http.server. The browser sends dropped files as base64
data URLs (JSON, no multipart). Processed assets are written into a real batch
dir under output/ and REGISTERED in that batch's registry, so the same
metadata pipeline used by the CLI can produce Adobe Stock CSV(s) from the UI.

Endpoints:
  POST /api/upscale    {name,data,source,to}      -> registers image, before/after urls
  POST /api/vectorize  {name,data,source,engine}  -> registers vector, before/preview + svg/eps
  GET  /api/registry                              -> current batch assets
  POST /api/metadata                              -> build per-kind CSV(s) + checklist
  GET  /files/<path>                              -> serve a file inside the batch dir

IP guardrail still applies: source=download is refused (409).
"""
from __future__ import annotations
import base64
import json
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from . import assets as assets_mod
from . import upscale as upscale_mod
from . import vectorize as vectorize_mod
from . import metadata as meta_mod

_CFG: Config = None          # set in serve()
_BATCH: Path = None          # current UI batch dir


def _b64_to_file(data_url: str, dest: Path) -> Path:
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(b64))
    return dest


INDEX_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>stockgen</title>
<style>
 :root{--bg:#0f1115;--fg:#e6e8ec;--mut:#8a90a0;--acc:#4aa9e6;--ok:#3fbf7f;--err:#e6584a;--card:#171a21}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:16px 22px;border-bottom:1px solid #232733;display:flex;gap:16px;align-items:center}
 header h1{font-size:17px;margin:0} .tabs{display:flex;gap:8px;margin-left:auto}
 .tab{padding:6px 14px;border:1px solid #2a2f3c;border-radius:8px;cursor:pointer;color:var(--mut)}
 .tab.on{color:var(--fg);border-color:var(--acc);background:#12202e}
 main{padding:22px;max-width:1100px;margin:0 auto}
 .batch{color:var(--mut);font-size:12px;margin-left:6px}
 .drop{border:2px dashed #2f3646;border-radius:14px;padding:44px;text-align:center;
   color:var(--mut);transition:.15s;cursor:pointer}
 .drop.hot{border-color:var(--acc);background:#101a24;color:var(--fg)}
 .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:16px 0}
 select,button{background:var(--card);color:var(--fg);border:1px solid #2a2f3c;
   border-radius:8px;padding:8px 12px;font-size:14px}
 button.go{background:var(--acc);color:#04121e;border:0;font-weight:600;cursor:pointer}
 button.go:disabled{opacity:.5;cursor:default}
 .status{margin:10px 0;color:var(--mut)} .status.err{color:var(--err)} .status.ok{color:var(--ok)}
 .cmp{position:relative;max-width:100%;margin-top:18px;border-radius:12px;overflow:hidden;
   background:#0a0c10;user-select:none;display:none}
 .cmp img{display:block;width:100%} .cmp .after{position:absolute;inset:0;overflow:hidden}
 .cmp .after img{position:absolute;top:0;left:0;height:100%;width:auto;max-width:none}
 .cmp .handle{position:absolute;top:0;bottom:0;width:2px;background:var(--acc);left:50%}
 .cmp .handle::after{content:"◀ ▶";position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
   background:var(--acc);color:#04121e;font-size:11px;padding:3px 6px;border-radius:10px;white-space:nowrap}
 .lbl{position:absolute;top:8px;padding:2px 8px;border-radius:6px;font-size:12px;background:#000a}
 .lbl.b{left:8px} .lbl.a{right:8px} .meta{color:var(--mut);margin-top:8px;font-size:13px}
 .links a{color:var(--acc);margin-right:14px}
 table{border-collapse:collapse;width:100%;margin-top:14px;font-size:13px}
 th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #232733}
 th{color:var(--mut);font-weight:600} .pill{padding:1px 8px;border-radius:10px;font-size:11px}
 .pill.ok{background:#12321f;color:var(--ok)} .pill.ai{background:#2a2410;color:#e6c05a}
 .hide{display:none}
</style></head><body>
<header><h1>stockgen</h1><span class="batch" id="batchName">…</span>
 <div class="tabs">
   <div class="tab on" data-t="upscale">Upscale → 4K</div>
   <div class="tab" data-t="vectorize">Raster → SVG</div>
   <div class="tab" data-t="export">Metadata / Export</div>
 </div>
</header>
<main>
 <div id="work">
  <div id="drop" class="drop">Drag &amp; drop an image here, or click to choose<br>
    <small>PNG / JPG / WEBP</small><input id="file" type="file" accept="image/*" hidden></div>
  <div class="row">
    <label>Source:
      <select id="source"><option value="original">original (my work)</option>
        <option value="ai_googleflow">ai_googleflow (paid plan)</option></select></label>
    <span id="opts"></span>
    <button id="go" class="go" disabled>Run</button>
  </div>
  <div id="status" class="status">No file loaded.</div>
  <div id="cmp" class="cmp">
    <img id="imgB" class="base">
    <div class="after"><img id="imgA"></div>
    <div class="handle" id="handle"></div>
    <span class="lbl b">BEFORE</span><span class="lbl a">AFTER</span>
  </div>
  <div id="meta" class="meta"></div>
  <div id="links" class="links meta"></div>
 </div>

 <div id="exportPane" class="hide">
  <div class="row">
    <button id="refresh" class="go" style="background:#2a2f3c;color:var(--fg)">Refresh assets</button>
    <button id="gen" class="go">Generate &amp; export CSV</button>
  </div>
  <div id="exStatus" class="status"></div>
  <div id="exLinks" class="links meta"></div>
  <table id="regTable"><thead><tr><th>File</th><th>Kind</th><th>Source</th><th>AI</th><th>Sellable</th></tr></thead>
    <tbody id="regBody"></tbody></table>
 </div>
</main>
<script>
let TAB="upscale", FILE=null;
const $=id=>document.getElementById(id);
const drop=$("drop"),file=$("file"),go=$("go"),status=$("status");
fetch("/api/registry").then(r=>r.json()).then(j=>{$("batchName").textContent="batch: "+j.batch;});
function setTab(t){TAB=t;document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x.dataset.t===t));
  const ex=t==="export";$("work").classList.toggle("hide",ex);$("exportPane").classList.toggle("hide",!ex);
  if(ex){loadReg();return;}
  $("opts").innerHTML = t==="vectorize"
    ? 'Engine: <select id="engine"><option value="vtracer">vtracer (color)</option><option value="potrace">potrace (mono)</option></select>'
    : 'Target: <select id="to"><option value="4k">4K</option></select>';
  resetCmp();}
document.querySelectorAll(".tab").forEach(x=>x.onclick=()=>setTab(x.dataset.t));
function resetCmp(){$("cmp").style.display="none";$("meta").textContent="";$("links").innerHTML="";}
drop.onclick=()=>file.click();
["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("hot")}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("hot")}));
drop.addEventListener("drop",ev=>{if(ev.dataTransfer.files[0])load(ev.dataTransfer.files[0])});
file.addEventListener("change",()=>{if(file.files[0])load(file.files[0])});
function load(f){const r=new FileReader();r.onload=()=>{FILE={name:f.name,data:r.result};
  status.textContent="Loaded: "+f.name;status.className="status";go.disabled=false;
  $("imgB").src=r.result;resetCmp();};r.readAsDataURL(f);}
go.onclick=async()=>{if(!FILE)return;go.disabled=true;status.className="status";
  status.textContent="Processing… (first upscale can take a while)";
  const body={name:FILE.name,data:FILE.data,source:$("source").value};
  if(TAB==="vectorize")body.engine=$("engine").value; else body.to=$("to").value;
  try{const res=await fetch("/api/"+TAB,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)});const j=await res.json();
    if(!res.ok){throw new Error(j.error||("HTTP "+res.status))}
    show(j);status.className="status ok";status.textContent="Done — added to batch. Go to Metadata / Export to make the CSV.";
  }catch(e){status.className="status err";status.textContent="✗ "+e.message}
  go.disabled=false;};
function show(j){$("imgB").src=j.before_url+"?t="+Date.now();
  $("imgA").src=(j.after_url||j.preview_url)+"?t="+Date.now();
  const cmp=$("cmp");cmp.style.display="block";
  const after=cmp.querySelector(".after"),handle=$("handle");
  function setW(p){p=Math.max(0,Math.min(100,p));after.style.width=p+"%";handle.style.left=p+"%";
    $("imgA").style.width=cmp.clientWidth+"px";}
  setW(50);
  let drag=false;const mv=e=>{if(!drag)return;const r=cmp.getBoundingClientRect();
    const x=((e.touches?e.touches[0].clientX:e.clientX)-r.left)/r.width*100;setW(x);};
  handle.onmousedown=()=>drag=true;window.onmouseup=()=>drag=false;window.onmousemove=mv;
  handle.ontouchstart=()=>drag=true;window.ontouchend=()=>drag=false;window.ontouchmove=mv;
  new ResizeObserver(()=>setW(parseFloat(after.style.width))).observe(cmp);
  $("meta").textContent=j.meta||"";
  let links="";if(j.svg_url)links+=`<a href="${j.svg_url}" download>SVG</a>`;
  if(j.eps_url)links+=`<a href="${j.eps_url}" download>EPS</a>`;
  if(j.after_url)links+=`<a href="${j.after_url}" download>4K image</a>`;
  $("links").innerHTML=links;}
async function loadReg(){const j=await(await fetch("/api/registry")).json();
  $("batchName").textContent="batch: "+j.batch;
  $("regBody").innerHTML=j.assets.map(a=>`<tr><td>${a.file}</td><td>${a.kind}</td><td>${a.source}</td>
    <td>${a.is_ai?'<span class="pill ai">AI</span>':''}</td>
    <td>${a.sellable?'<span class="pill ok">✓</span>':'✗'}</td></tr>`).join("")
    || '<tr><td colspan=5 style="color:var(--mut)">No assets yet — upscale or vectorize something first.</td></tr>';}
$("refresh").onclick=loadReg;
$("gen").onclick=async()=>{$("exStatus").className="status";$("exStatus").textContent="Generating…";
  try{const j=await(await fetch("/api/metadata",{method:"POST"})).json();
    if(j.error)throw new Error(j.error);
    $("exStatus").className="status ok";$("exStatus").textContent="Exported "+j.total+" asset(s).";
    let l="";for(const [k,u] of Object.entries(j.csv))l+=`<a href="${u}" download>metadata_${k}.csv</a>`;
    if(j.checklist_url)l+=`<a href="${j.checklist_url}" download>upload_checklist.txt</a>`;
    $("exLinks").innerHTML=l;loadReg();
  }catch(e){$("exStatus").className="status err";$("exStatus").textContent="✗ "+e.message}};
setTab("upscale");
</script></body></html>"""


def _make_handler():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # ---- GET ----
        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                return self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            if self.path == "/api/registry":
                return self._send(200, json.dumps(self._registry()))
            if self.path.startswith("/files/"):
                return self._serve_file(self.path[len("/files/"):].split("?", 1)[0])
            return self._send(404, json.dumps({"error": "not found"}))

        def _serve_file(self, name):
            if ".." in name:
                return self._send(404, json.dumps({"error": "not found"}))
            fp = (_BATCH / name).resolve()
            if _BATCH.resolve() not in fp.parents or not fp.exists():
                return self._send(404, json.dumps({"error": "not found"}))
            ext = fp.suffix.lower().lstrip(".")
            ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                     "webp": "image/webp", "svg": "image/svg+xml",
                     "eps": "application/postscript", "csv": "text/csv",
                     "txt": "text/plain"}.get(ext, "application/octet-stream")
            return self._send(200, fp.read_bytes(), ctype)

        # ---- POST ----
        def do_POST(self):
            body = {}
            if self.path in ("/api/upscale", "/api/vectorize"):
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(n) or b"{}")
                except Exception as e:
                    return self._send(400, json.dumps({"error": f"bad request: {e}"}))
            try:
                if self.path == "/api/upscale":
                    return self._send(200, json.dumps(self._upscale(body)))
                if self.path == "/api/vectorize":
                    return self._send(200, json.dumps(self._vectorize(body)))
                if self.path == "/api/metadata":
                    return self._send(200, json.dumps(self._metadata()))
                return self._send(404, json.dumps({"error": "unknown endpoint"}))
            except assets_mod.GuardrailError as e:
                return self._send(409, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))

        def _next_idx(self, reg, kind):
            return len(reg.of_kind(kind)) + 1

        def _upscale(self, req):
            source = req.get("source", "original")
            upscale_mod._assert_source_ok(source)
            reg = assets_mod.Registry.load(_BATCH)
            idx = self._next_idx(reg, assets_mod.KIND_IMAGE)
            src = _b64_to_file(req["data"], _BATCH / "_src" / ("in_" + Path(req["name"]).name))
            out = _BATCH / "image" / f"img_{idx:03d}.jpg"
            info = upscale_mod.upscale_image(src, out, req.get("to", "4k"))
            reg.add(assets_mod.Asset(
                file=f"image/{out.name}", kind=assets_mod.KIND_IMAGE, source=source,
                sketch="gradient", seed=idx))
            reg.save()
            return {"before_url": f"/files/_src/{src.name}", "after_url": f"/files/image/{out.name}",
                    "meta": f"{info['from']} → {info['to']}  ({info.get('engine','')})  · added as image/{out.name}"}

        def _vectorize(self, req):
            source = req.get("source", "original")
            reg = assets_mod.Registry.load(_BATCH)
            idx = self._next_idx(reg, assets_mod.KIND_VECTOR)
            src = _b64_to_file(req["data"], _BATCH / "_src" / ("in_" + Path(req["name"]).name))
            info = vectorize_mod.vectorize(src, _BATCH / "vector", idx, source,
                                           engine=req.get("engine", "vtracer"))
            reg.add(assets_mod.Asset(
                file=f"vector/{info['file']}", kind=assets_mod.KIND_VECTOR, source=source,
                sketch="icons", seed=idx))
            reg.save()
            return {"before_url": f"/files/_src/{src.name}",
                    "preview_url": f"/files/vector/{info['preview']}",
                    "svg_url": f"/files/vector/{info['svg']}",
                    "eps_url": f"/files/vector/{info['file']}",
                    "meta": f"traced with {info['engine']}  · added as vector/{info['file']}"}

        def _registry(self):
            reg = assets_mod.Registry.load(_BATCH)
            return {"batch": _BATCH.name,
                    "assets": [{"file": a.file, "kind": a.kind, "source": a.source,
                                "is_ai": a.is_ai, "sellable": a.sellable} for a in reg.assets]}

        def _metadata(self):
            reg = assets_mod.Registry.load(_BATCH)
            errs = reg.validate()
            if errs:
                return {"error": "guardrail: " + errs[0]}
            if not reg.assets:
                return {"error": "no assets in batch yet"}
            written = meta_mod.build_per_kind_csvs(_CFG, reg, _BATCH)
            # upload checklist (lazy import to avoid circular import with main)
            from .main import _write_upload_checklist
            _write_upload_checklist(_BATCH, reg)
            return {"total": len(reg.assets),
                    "csv": {k: f"/files/{p.name}" for k, p in written.items()},
                    "checklist_url": "/files/upload_checklist.txt"}
    return H


def _resolve_batch(cfg: Config, batch) -> Path:
    """Resolve a --batch value: absolute/relative path, bare name under output/,
    or None -> a fresh timestamped batch. Existing dirs are reused (assets append)."""
    if not batch:
        return cfg.output_dir / datetime.now().strftime("batch_ui_%Y%m%d_%H%M%S")
    p = Path(batch)
    if not p.is_absolute() and not p.exists():
        p = cfg.output_dir / batch     # bare name -> under output/
    return p


def serve(port: int = 8765, open_browser: bool = True, batch: Path | None = None) -> int:
    global _CFG, _BATCH
    _CFG = Config.load(None)
    _BATCH = _resolve_batch(_CFG, batch)
    existed = _BATCH.exists()
    _BATCH.mkdir(parents=True, exist_ok=True)
    n = len(assets_mod.Registry.load(_BATCH).assets) if existed else 0
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler())
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    tag = f" (resuming, {n} asset(s))" if existed else " (new)"
    print(f"stockgen UI → {url}   batch: {_BATCH}{tag}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
