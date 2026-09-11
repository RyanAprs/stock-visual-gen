"""Local web UI for stockgen v2 — drag&drop + before/after preview.

Zero extra deps: uses stdlib http.server. The browser sends the dropped file as
a base64 data URL (JSON) so we avoid multipart parsing. Results are written into
a per-session working dir and served back over /files/.

Actions exposed:
  POST /api/upscale   {name, data, source, to}      -> before/after image URLs
  POST /api/vectorize {name, data, source, engine}  -> before img + traced SVG/EPS/preview

The IP guardrail still applies: source=download is refused (409).
"""
from __future__ import annotations
import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import assets as assets_mod
from . import upscale as upscale_mod
from . import vectorize as vectorize_mod

_WORK: Path = Path("/tmp/stockgen_ui")


def _b64_to_file(data_url: str, dest: Path) -> Path:
    """Decode a 'data:<mime>;base64,....' URL (or bare base64) to dest."""
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
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
</style></head><body>
<header><h1>stockgen</h1><span style="color:var(--mut)">local studio</span>
 <div class="tabs">
   <div class="tab on" data-t="upscale">Upscale → 4K</div>
   <div class="tab" data-t="vectorize">Raster → SVG</div>
 </div>
</header>
<main>
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
</main>
<script>
let TAB="upscale", FILE=null;
const $=id=>document.getElementById(id);
const drop=$("drop"),file=$("file"),go=$("go"),status=$("status");
function setTab(t){TAB=t;document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x.dataset.t===t));
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
    show(j);status.className="status ok";status.textContent="Done.";
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
setTab("upscale");
</script></body></html>"""


def _make_handler(workdir: Path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                return self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            if self.path.startswith("/files/"):
                name = self.path[len("/files/"):].split("?", 1)[0]
                fp = workdir / name
                if not fp.exists() or ".." in name:
                    return self._send(404, json.dumps({"error": "not found"}))
                ext = fp.suffix.lower()
                ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                         "webp": "image/webp", "svg": "image/svg+xml",
                         "eps": "application/postscript"}.get(ext.lstrip("."), "application/octet-stream")
                return self._send(200, fp.read_bytes(), ctype)
            return self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception as e:
                return self._send(400, json.dumps({"error": f"bad request: {e}"}))
            try:
                if self.path == "/api/upscale":
                    return self._send(200, json.dumps(self._upscale(req)))
                if self.path == "/api/vectorize":
                    return self._send(200, json.dumps(self._vectorize(req)))
                return self._send(404, json.dumps({"error": "unknown endpoint"}))
            except assets_mod.GuardrailError as e:
                return self._send(409, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))

        def _upscale(self, req):
            src_name = "in_" + Path(req["name"]).name
            src = _b64_to_file(req["data"], workdir / src_name)
            upscale_mod._assert_source_ok(req.get("source", "original"))
            out = workdir / ("out_" + Path(req["name"]).stem + "_4k.jpg")
            info = upscale_mod.upscale_image(src, out, req.get("to", "4k"))
            return {"before_url": f"/files/{src.name}", "after_url": f"/files/{out.name}",
                    "meta": f"{info['from']} → {info['to']}  ({info.get('engine','')})"}

        def _vectorize(self, req):
            src_name = "in_" + Path(req["name"]).name
            src = _b64_to_file(req["data"], workdir / src_name)
            source = req.get("source", "original")
            info = vectorize_mod.vectorize(src, workdir, 900, source,
                                           engine=req.get("engine", "vtracer"))
            return {"before_url": f"/files/{src.name}",
                    "preview_url": f"/files/{info['preview']}",
                    "svg_url": f"/files/{info['svg']}", "eps_url": f"/files/{info['file']}",
                    "meta": f"traced with {info['engine']}"}
    return H


def serve(port: int = 8765, open_browser: bool = True, workdir: Path | None = None) -> int:
    global _WORK
    _WORK = workdir or _WORK
    _WORK.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(_WORK))
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"stockgen UI → {url}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
