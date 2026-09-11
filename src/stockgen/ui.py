"""Local web UI for stockgen v2 — drag&drop, before/after preview, CSV export.

Zero extra deps: stdlib http.server. The browser sends dropped files as base64
data URLs (JSON, no multipart). Processed assets are written into a real batch
dir under output/ and REGISTERED in that batch's registry, so the same
metadata pipeline used by the CLI can produce Adobe Stock CSV(s) from the UI.

Endpoints:
  POST /api/upscale    {name,data,source,to}      -> single image upscale
  POST /api/vectorize  {name,data,source,engine}  -> single raster->vector
  POST /api/batch      {files:[{name,data,desc}],source,kind,engine,to} -> batch (puluhan aset)
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
import subprocess

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
 select,button,input{background:var(--card);color:var(--fg);border:1px solid #2a2f3c;
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
 video{width:100%;border-radius:12px;background:#0a0c10;margin-top:12px}
 .vid-cmp{display:none;gap:16px;margin-top:18px}
 .vid-cmp>div{flex:1;min-width:0} .vid-cmp video{width:100%}
 .vid-cmp .lbl{position:static;display:inline-block;margin-bottom:6px}
 .info-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin:12px 0}
 .info-grid>div{background:var(--card);padding:8px 12px;border-radius:8px}
 .info-grid .k{font-size:11px;color:var(--mut)} .info-grid .v{font-size:15px;font-weight:600}
 .queue{margin-top:14px}
 .qrow{display:flex;gap:10px;align-items:center;padding:8px 10px;border-bottom:1px solid #232733;font-size:13px}
 .qrow .qname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .qrow .qkind{color:var(--mut);font-size:11px;min-width:52px;text-align:center}
 .qrow .qst{font-size:11px;padding:2px 8px;border-radius:10px;min-width:68px;text-align:center}
 .qst-wait{background:#1a1d24;color:var(--mut)} .qst-run{background:#12202e;color:var(--acc)}
 .qst-ok{background:#12321f;color:var(--ok)} .qst-err{background:#2a1210;color:var(--err)}
 .bar{height:4px;background:#1e2330;border-radius:2px;overflow:hidden;margin:8px 0 14px}
 .bar>i{display:block;height:100%;background:var(--acc);width:0;transition:.3s}

</style></head><body>
<header><h1>stockgen</h1><span class="batch" id="batchName">…</span>
 <div class="tabs">
   <div class="tab on" data-t="batch">📦 Batch</div>
   <div class="tab" data-t="upscale">Upscale → 4K</div>
   <div class="tab" data-t="vectorize">Raster → SVG</div>
   <div class="tab" data-t="video">Video</div>
   <div class="tab" data-t="export">Metadata / Export</div>
 </div>
</header>
<main>
 <div id="batchPane">
  <div id="batchDrop" class="drop">Drag &amp; drop <b>puluhan aset</b> sekaligus di sini, atau klik untuk pilih<br>
    <small>PNG / JPG / WEBP / MP4 / MOV — bisa campur image + video</small>
    <input id="batchFile" type="file" accept="image/*,video/*" hidden multiple></div>
  <div class="row">
    <label>Kind: <select id="batchKind"><option value="auto">auto (by file type)</option><option value="image">image (upscale → 4K)</option><option value="video">video (native prepare)</option><option value="vector">vector (raster → SVG)</option></select></label>
    <label>Source: <select id="batchSource"><option value="original">original (my work)</option><option value="ai_googleflow">ai_googleflow (paid plan)</option></select></label>
    <span id="batchOpts"></span>
    <button id="batchGo" class="go" disabled>Proses batch (1 klik)</button>
    <button id="batchClear" style="background:#2a1210;color:var(--err);border-color:#3a2020" disabled>Clear</button>
  </div>
  <div id="batchStatus" class="status">Belum ada file — drop puluhan aset sekaligus, lalu klik Proses batch.</div>
  <div class="bar" style="display:none" id="batchBar"><i id="batchBarFill"></i></div>
  <div id="batchQueue" class="queue"></div>
  <div id="batchLinks" class="links meta"></div>
 </div>

 <div id="work" class="hide">
  <div id="drop" class="drop">Drag &amp; drop an image here, or click to choose<br>
    <small>PNG / JPG / WEBP</small><input id="file" type="file" accept="image/*" hidden></div>
  <div class="row">
    <label>Source:
      <select id="source"><option value="original">original (my work)</option>
        <option value="ai_googleflow">ai_googleflow (paid plan)</option></select></label>
    <span id="opts"></span>
    <label style="flex:1;min-width:200px">Describe it (for title/keywords):
      <input id="desc" placeholder="optional — AI describes it automatically" style="width:100%"></label>
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

 <div id="videoPane" class="hide">
  <div id="vDrop" class="drop">Drag &amp; drop a video here, or click to choose<br>
    <small>MP4 / MOV / WEBM</small><input id="vFile" type="file" accept="video/*" hidden></div>
  <div class="row">
    <label>Source:
      <select id="vSource"><option value="original">original (my work)</option>
        <option value="ai_googleflow">ai_googleflow (paid plan)</option></select></label>
    <label style="flex:1;min-width:200px">Describe it (for title/keywords):
      <input id="vDesc" placeholder="optional — AI describes it automatically" style="width:100%"></label>
    <button id="vUp" class="go" disabled>Upscale → 4K</button>
    <button id="vPrep" class="go" disabled style="background:var(--ok);color:#04121e">Prepare native for Adobe ✓</button>
  </div>
  <div class="meta" style="margin-top:-8px">Adobe forbids up-res (HD→4K triggers their low-quality warning). For Adobe, always submit native resolution — use the green button.</div>
  <div id="vInfo" class="info-grid"></div>
  <div id="vStatus" class="status"></div>
  <video id="vBefore" controls style="display:none"></video>
  <div id="vCmp" class="vid-cmp">
    <div><span class="lbl b">BEFORE</span><video id="vCmpB" controls></video></div>
    <div><span class="lbl a">AFTER (4K)</span><video id="vCmpA" controls></video></div>
  </div>
  <div id="vLinks" class="links meta"></div>
 </div>

 <div id="exportPane" class="hide">
  <div class="row">
    <button id="refresh" class="go" style="background:#2a2f3c;color:var(--fg)">Refresh assets</button>
    <button id="gen" class="go">Generate &amp; export CSV</button>
  </div>
  <div id="exStatus" class="status"></div>
  <div id="exLinks" class="links meta"></div>
  <table id="regTable"><thead><tr><th>File</th><th>Kind</th><th>Description</th><th>Source</th><th>AI</th><th>Sellable</th></tr></thead>
    <tbody id="regBody"></tbody></table>
 </div>
</main>
<script>
let TAB="batch", FILE=null, VFILE=null, BATCH_FILES=[];
const $=id=>document.getElementById(id);
const drop=$("drop"),file=$("file"),go=$("go"),status=$("status");
const vDrop=$("vDrop"),vFile=$("vFile"),vUp=$("vUp"),vPrep=$("vPrep"),vStatus=$("vStatus");
const batchDrop=$("batchDrop"),batchFile=$("batchFile"),batchGo=$("batchGo"),batchClear=$("batchClear"),batchStatus=$("batchStatus");
fetch("/api/registry").then(r=>r.json()).then(j=>{$("batchName").textContent="batch: "+j.batch;});
function isImage(n){return /\.(png|jpg|jpeg|webp)$/i.test(n);}
function isVideo(n){return /\.(mp4|mov|webm|m4v)$/i.test(n);}
function kindFor(name, forced){if(forced && forced!=="auto") return forced; if(isVideo(name)) return "video"; if(isImage(name)) return "image"; return "image";}
function setTab(t){TAB=t;document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x.dataset.t===t));
  const ex=t==="export",vid=t==="video",up=t==="upscale",vec=t==="vectorize",bat=t==="batch";
  $("work").classList.toggle("hide",ex||vid||bat);$("exportPane").classList.toggle("hide",!ex);
  $("videoPane").classList.toggle("hide",!vid);$("batchPane").classList.toggle("hide",!bat);
  if(ex){loadReg();return;}
  if(vid)return;
  if(bat){updateBatchOpts();return;}
  $("opts").innerHTML = vec
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
  const body={name:FILE.name,data:FILE.data,source:$("source").value,desc:$("desc").value.trim()};
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
  $("regBody").innerHTML=j.assets.map(a=>`<tr><td>${a.file}</td><td>${a.kind}</td><td>${a.desc||'<span style="color:var(--mut)">—</span>'}</td><td>${a.source}</td>
    <td>${a.is_ai?'<span class="pill ai">AI</span>':''}</td>
    <td>${a.sellable?'<span class="pill ok">✓</span>':'✗'}</td></tr>`).join("")
    || '<tr><td colspan=6 style="color:var(--mut)">No assets yet — upscale or vectorize something first.</td></tr>';}
$("refresh").onclick=loadReg;
$("gen").onclick=async()=>{$("exStatus").className="status";$("exStatus").textContent="Generating…";
  try{const j=await(await fetch("/api/metadata",{method:"POST"})).json();
    if(j.error)throw new Error(j.error);
    $("exStatus").className="status ok";$("exStatus").textContent="Exported "+j.total+" asset(s).";
    let l="";for(const [k,u] of Object.entries(j.csv))l+=`<a href="${u}" download>metadata_${k}.csv</a>`;
    if(j.checklist_url)l+=`<a href="${j.checklist_url}" download>upload_checklist.txt</a>`;
    $("exLinks").innerHTML=l;loadReg();
  }catch(e){$("exStatus").className="status err";$("exStatus").textContent="✗ "+e.message}};
/* ---- VIDEO TAB ---- */
vDrop.onclick=()=>vFile.click();
["dragover","dragenter"].forEach(e=>vDrop.addEventListener(e,ev=>{ev.preventDefault();vDrop.classList.add("hot")}));
["dragleave","drop"].forEach(e=>vDrop.addEventListener(e,ev=>{ev.preventDefault();vDrop.classList.remove("hot")}));
vDrop.addEventListener("drop",ev=>{if(ev.dataTransfer.files[0])loadV(ev.dataTransfer.files[0])});
vFile.addEventListener("change",()=>{if(vFile.files[0])loadV(vFile.files[0])});
function loadV(f){
  VFILE=f; vUp.disabled=false; vPrep.disabled=false;
  vStatus.textContent="Loaded: "+f.name+" ("+Math.round(f.size/1024/1024)+" MB)";vStatus.className="status";
  $("vBefore").src=URL.createObjectURL(f);$("vBefore").style.display="block";
  $("vCmp").style.display="none";$("vInfo").innerHTML="";$("vLinks").innerHTML="";
  /* probe for info */
  const r=new FileReader();r.onload=async()=>{
    try{const res=await fetch("/api/video_probe",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:f.name,data:r.result})});const j=await res.json();
      if(j.width){$("vInfo").innerHTML=
        `<div><div class="k">Resolution</div><div class="v">${j.width}×${j.height}</div></div>
         <div><div class="k">Duration</div><div class="v">${j.duration}s</div></div>
         <div><div class="k">FPS</div><div class="v">${j.fps}</div></div>
         <div><div class="k">Codec</div><div class="v">${j.codec||'—'}</div></div>
         <div><div class="k">4K ready</div><div class="v">${j.is_4k?'✓ yes':'✗ no'}</div></div>`}
    }catch(e){}};r.readAsDataURL(f);}
vUp.onclick=async()=>{if(!VFILE)return;vUp.disabled=true;vStatus.className="status";
  vStatus.textContent="Upscaling… this can take several minutes for large videos.";
  const r=new FileReader();r.onload=async()=>{
    try{const res=await fetch("/api/video_upscale",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:VFILE.name,data:r.result,source:$("vSource").value,desc:$("vDesc").value.trim()})});
      const j=await res.json();if(!res.ok)throw new Error(j.error||"HTTP "+res.status);
      $("vCmpB").src=$("vBefore").src;
      $("vCmpA").src=j.after_url+"?t="+Date.now();
      $("vCmp").style.display="flex";$("vBefore").style.display="none";
      $("vLinks").innerHTML=`<a href="${j.after_url}" download>Download 4K video</a>`;
      vStatus.className="status ok";vStatus.textContent="Done — "+j.meta+" · added to batch.";
    }catch(e){vStatus.className="status err";vStatus.textContent="✗ "+e.message}
    vUp.disabled=false;};r.readAsDataURL(VFILE);};
vPrep.onclick=async()=>{if(!VFILE)return;vPrep.disabled=true;vUp.disabled=true;vStatus.className="status";
  vStatus.textContent="Preparing native file…";
  const r=new FileReader();r.onload=async()=>{
    try{const res=await fetch("/api/video_prepare",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:VFILE.name,data:r.result,source:$("vSource").value,desc:$("vDesc").value.trim()})});
      const j=await res.json();if(!res.ok)throw new Error(j.error||"HTTP "+res.status);
      $("vBefore").style.display="block";$("vCmp").style.display="none";
      $("vLinks").innerHTML=`<a href="${j.after_url}" download>Download Adobe-ready file</a>`;
      vStatus.className="status ok";vStatus.textContent="Done — "+j.meta+" · submit THIS file to Adobe.";
    }catch(e){vStatus.className="status err";vStatus.textContent="✗ "+e.message}
    vPrep.disabled=false;vUp.disabled=false;};r.readAsDataURL(VFILE);};
/* ---- BATCH TAB (puluhan aset sekaligus) ---- */
function updateBatchOpts(){
  const k=$("batchKind").value;
  if(k==="vector") $("batchOpts").innerHTML='Engine: <select id="batchEngine"><option value="vtracer">vtracer (color)</option><option value="potrace">potrace (mono)</option></select>';
  else if(k==="image") $("batchOpts").innerHTML='Target: <select id="batchTo"><option value="4k">4K</option></select>';
  else $("batchOpts").innerHTML='<span style="color:var(--mut);font-size:12px">auto: image→4K, video→native, raster dipilih → SVG</span>';
}
$("batchKind").addEventListener("change", updateBatchOpts);
function renderQueue(){
  const q=$("batchQueue"), n=BATCH_FILES.length;
  if(!n){q.innerHTML="";batchStatus.textContent="Belum ada file — drop puluhan aset sekaligus, lalu klik Proses batch.";batchStatus.className="status";batchGo.disabled=true;batchClear.disabled=true;$("batchBar").style.display="none";return;}
  batchGo.disabled=false;batchClear.disabled=false;
  batchStatus.textContent=n+" file siap — klik Proses batch untuk proses semua sekaligus.";batchStatus.className="status";
  q.innerHTML=BATCH_FILES.map((f,i)=>{
    const st=f._st||"wait", label={wait:"menunggu",run:"proses…",ok:"✓ selesai",err:"✗ gagal"}[st]||st;
    const cls={wait:"qst-wait",run:"qst-run",ok:"qst-ok",err:"qst-err"}[st]||"qst-wait";
    const kind=kindFor(f.name,$("batchKind").value);
    const err=f._err?` title="${f._err.replace(/\"/g,'&quot;')}"`:"";
    return `<div class="qrow" data-i="${i}"><span class="qname">${f.name}</span><span class="qkind">${kind}</span><span class="qst ${cls}"${err}>${label}</span></div>`;
  }).join("");
}
function enqueueFiles(list){
  for(const f of list){
    if(!isImage(f.name) && !isVideo(f.name)){continue;}
    const r=new FileReader();
    r.onload=()=>{BATCH_FILES.push({name:f.name,data:r.result,_st:"wait"});renderQueue();};
    r.readAsDataURL(f);
  }
  // render after a short delay for first file
  setTimeout(renderQueue, 80);
}
batchDrop.onclick=()=>batchFile.click();
["dragover","dragenter"].forEach(e=>batchDrop.addEventListener(e,ev=>{ev.preventDefault();batchDrop.classList.add("hot")}));
["dragleave","drop"].forEach(e=>batchDrop.addEventListener(e,ev=>{ev.preventDefault();batchDrop.classList.remove("hot")}));
batchDrop.addEventListener("drop",ev=>{if(ev.dataTransfer.files.length) enqueueFiles([...ev.dataTransfer.files]);});
batchFile.addEventListener("change",()=>{if(batchFile.files.length) enqueueFiles([...batchFile.files]); batchFile.value="";});
batchClear.onclick=()=>{BATCH_FILES=[];renderQueue();$("batchLinks").innerHTML="";$("batchBar").style.display="none";};
batchGo.onclick=async()=>{
  if(!BATCH_FILES.length) return;
  batchGo.disabled=true;batchClear.disabled=true;batchStatus.textContent="Memproses "+BATCH_FILES.length+" aset… jangan tutup tab ini.";
  batchStatus.className="status";$("batchBar").style.display="block";$("batchBarFill").style.width="0%";$("batchLinks").innerHTML="";
  const body={files: BATCH_FILES.map(f=>({name:f.name,data:f.data})), source:$("batchSource").value, kind:$("batchKind").value};
  const ek=$("batchEngine"); if(ek) body.engine=ek.value;
  const tk=$("batchTo"); if(tk) body.to=tk.value;
  // optimistic: mark all as run
  BATCH_FILES.forEach(f=>f._st="run");renderQueue();
  try{
    const res=await fetch("/api/batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const j=await res.json();
    if(!res.ok) throw new Error(j.error||("HTTP "+res.status));
    // update per-file status from server response
    (j.results||[]).forEach((r,i)=>{if(BATCH_FILES[i]){BATCH_FILES[i]._st=r.ok?"ok":"err";BATCH_FILES[i]._err=r.error||"";}});
    renderQueue();
    $("batchBarFill").style.width="100%";
    const ok=(j.results||[]).filter(r=>r.ok).length, fail=j.results.length-ok;
    batchStatus.className=fail?"status err":"status ok";
    batchStatus.textContent="Selesai: "+ok+" berhasil, "+fail+" gagal dari "+j.results.length+" aset. "+(fail?"Cek yang gagal — lalu buka Metadata / Export.":"Buka Metadata / Export untuk generate CSV.");
    // keep successful files in queue for visibility, allow re-run of failed
    if(ok && !fail) BATCH_FILES=[];
    else BATCH_FILES=BATCH_FILES.filter(f=>f._st==="err");
    let links=""; if(j.csv) for(const [k,u] of Object.entries(j.csv)) links+=`<a href="${u}" download>metadata_${k}.csv</a>`;
    if(j.checklist_url) links+=`<a href="${j.checklist_url}" download>upload_checklist.txt</a>`;
    if(links) links+='<span style="color:var(--mut);font-size:12px"> — atau buka tab Metadata / Export untuk review</span>';
    $("batchLinks").innerHTML=links;
    fetch("/api/registry").then(r=>r.json()).then(j=>{$("batchName").textContent="batch: "+j.batch;});
  }catch(e){batchStatus.className="status err";batchStatus.textContent="✗ "+e.message; BATCH_FILES.forEach(f=>{if(f._st==="run") f._st="err";});renderQueue();}
  batchGo.disabled=false;batchClear.disabled=false;
};
setTab("batch");
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
                     "txt": "text/plain", "mp4": "video/mp4", "mov": "video/quicktime",
                     "webm": "video/webm"}.get(ext, "application/octet-stream")
            return self._send(200, fp.read_bytes(), ctype)

        # ---- POST ----
        def do_POST(self):
            body = {}
            if self.path in ("/api/upscale", "/api/vectorize", "/api/video_probe", "/api/video_upscale",
                               "/api/video_prepare", "/api/batch"):
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
                if self.path == "/api/video_probe":
                    return self._send(200, json.dumps(self._video_probe(body)))
                if self.path == "/api/video_upscale":
                    return self._send(200, json.dumps(self._video_upscale(body)))
                if self.path == "/api/video_prepare":
                    return self._send(200, json.dumps(self._video_prepare(body)))
                if self.path == "/api/batch":
                    return self._send(200, json.dumps(self._batch(body)))
                if self.path == "/api/metadata":
                    return self._send(200, json.dumps(self._metadata()))
                return self._send(404, json.dumps({"error": "unknown endpoint"}))
            except assets_mod.GuardrailError as e:
                return self._send(409, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))

        def _next_idx(self, reg, kind):
            return len(reg.of_kind(kind)) + 1

        def _desc_of(self, req):
            return (req.get("desc") or "").strip() or meta_mod.desc_from_filename(req.get("name", ""))

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
                sketch="gradient", seed=idx, desc=self._desc_of(req)))
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
                sketch="icons", seed=idx, desc=self._desc_of(req)))
            reg.save()
            return {"before_url": f"/files/_src/{src.name}",
                    "preview_url": f"/files/vector/{info['preview']}",
                    "svg_url": f"/files/vector/{info['svg']}",
                    "eps_url": f"/files/vector/{info['file']}",
                    "meta": f"traced with {info['engine']}  · added as vector/{info['file']}"}

        def _video_probe(self, req):
            """Save video, run ffprobe, return resolution/fps/duration/codec."""
            src = _b64_to_file(req["data"], _BATCH / "_src" / ("in_" + Path(req["name"]).name))
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate,codec_name,duration",
                 "-show_entries", "format=duration",
                 "-of", "json", str(src)],
                capture_output=True, text=True)
            info = json.loads(out.stdout or "{}")
            st = (info.get("streams") or [{}])[0]
            w = int(st.get("width") or 0)
            h = int(st.get("height") or 0)
            dur = st.get("duration") or (info.get("format") or {}).get("duration") or "?"
            if dur != "?":
                dur = f"{float(dur):.1f}"
            rfr = st.get("r_frame_rate", "0/1")
            try:
                num, den = rfr.split("/")
                fps = f"{int(num)/int(den):.2f}"
            except Exception:
                fps = rfr
            return {"width": w, "height": h, "duration": dur, "fps": fps,
                    "codec": st.get("codec_name", ""),
                    "is_4k": (w >= 3840 or h >= 3840)}

        def _video_upscale(self, req):
            """Upscale video to 4K, register in batch."""
            source = req.get("source", "original")
            upscale_mod._assert_source_ok(source)
            reg = assets_mod.Registry.load(_BATCH)
            idx = self._next_idx(reg, assets_mod.KIND_VIDEO)
            src = _b64_to_file(req["data"], _BATCH / "_src" / ("in_" + Path(req["name"]).name))
            out = _BATCH / "video" / f"vid_{idx:03d}_4k.mp4"
            info = upscale_mod.upscale_video(src, out)
            is_ai = source in assets_mod.AI_SOURCES
            reg.add(assets_mod.Asset(
                file=f"video/{out.name}", kind=assets_mod.KIND_VIDEO, source=source,
                is_ai=is_ai, sketch="gradient", seed=idx, desc=self._desc_of(req)))
            reg.save()
            return {"after_url": f"/files/video/{out.name}",
                    "meta": f"{info['from']} → {info['to']}  · added as video/{out.name}"}

        def _video_prepare(self, req):
            """Re-encode at NATIVE resolution — the Adobe-compliant path."""
            source = req.get("source", "original")
            upscale_mod._assert_source_ok(source)
            reg = assets_mod.Registry.load(_BATCH)
            idx = self._next_idx(reg, assets_mod.KIND_VIDEO)
            src = _b64_to_file(req["data"], _BATCH / "_src" / ("in_" + Path(req["name"]).name))
            out = _BATCH / "video" / f"vid_{idx:03d}_native.mp4"
            info = upscale_mod.prepare_native_video(src, out)
            is_ai = source in assets_mod.AI_SOURCES
            reg.add(assets_mod.Asset(
                file=f"video/{out.name}", kind=assets_mod.KIND_VIDEO, source=source,
                is_ai=is_ai, sketch="gradient", seed=idx, desc=self._desc_of(req)))
            reg.save()
            return {"after_url": f"/files/video/{out.name}",
                    "meta": f"native {info['to']} (CRF14)  · added as video/{out.name}"}

        def _batch(self, req):
            """Batch: process puluhan aset sekaligus — one click, mixed image+video+vector.

            req = {files:[{name,data,desc?}], source, kind:auto|image|video|vector, engine?, to?}
            Returns {results:[{name,kind,ok,file?,error?}], total, csv?, checklist_url?}
            Each file is processed sequentially; one failure doesn't abort the rest.
            """
            source = req.get("source", "original")
            try:
                upscale_mod._assert_source_ok(source)
            except assets_mod.GuardrailError as e:
                return {"error": str(e), "results": []}
            files = req.get("files") or []
            if not files:
                return {"error": "no files in batch (need files:[{name,data}])", "results": []}
            if len(files) > 100:
                return {"error": f"batch too large: {len(files)} files (max 100 per batch)", "results": []}
            kind_forced = (req.get("kind") or "auto").strip().lower()
            engine = req.get("engine", "vtracer")
            to = req.get("to", "4k")
            is_ai = source in assets_mod.AI_SOURCES
            results = []
            for item in files:
                name = (item.get("name") or "unnamed").strip()
                data = item.get("data") or ""
                desc = (item.get("desc") or "").strip() or meta_mod.desc_from_filename(name)
                if not data:
                    results.append({"name": name, "ok": False, "error": "missing data"})
                    continue
                # detect kind
                ext = Path(name).suffix.lower()
                if kind_forced == "vector":
                    kind = assets_mod.KIND_VECTOR
                elif kind_forced == "image":
                    kind = assets_mod.KIND_IMAGE
                elif kind_forced == "video":
                    kind = assets_mod.KIND_VIDEO
                else:  # auto
                    if ext in (".mp4", ".mov", ".m4v", ".webm"):
                        kind = assets_mod.KIND_VIDEO
                    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
                        # svg input that's forced auto but looks like vector source -> image unless explicitly vector
                        kind = assets_mod.KIND_IMAGE
                    else:
                        kind = assets_mod.KIND_IMAGE
                try:
                    reg = assets_mod.Registry.load(_BATCH)
                    idx = len(reg.of_kind(kind)) + 1
                    src = _b64_to_file(data, _BATCH / "_src" / ("in_" + Path(name).name))
                    if kind == assets_mod.KIND_VIDEO:
                        out = _BATCH / "video" / f"vid_{idx:03d}_native.mp4"
                        info = upscale_mod.prepare_native_video(src, out)
                        reg.add(assets_mod.Asset(
                            file=f"video/{out.name}", kind=kind, source=source,
                            is_ai=is_ai, sketch="auto", seed=idx, desc=desc))
                        reg.save()
                        results.append({"name": name, "kind": kind, "ok": True, "file": f"video/{out.name}", "meta": f"native {info['to']}"})
                    elif kind == assets_mod.KIND_VECTOR:
                        info = vectorize_mod.vectorize(src, _BATCH / "vector", idx, source, engine=engine)
                        reg.add(assets_mod.Asset(
                            file=f"vector/{info['file']}", kind=kind, source=source,
                            sketch="icons", seed=idx, desc=desc))
                        reg.save()
                        results.append({"name": name, "kind": kind, "ok": True, "file": f"vector/{info['file']}", "meta": f"traced {info['engine']}"})
                    else:  # image -> upscale to 4K
                        out = _BATCH / "image" / f"img_{idx:03d}.jpg"
                        info = upscale_mod.upscale_image(src, out, to)
                        reg.add(assets_mod.Asset(
                            file=f"image/{out.name}", kind=kind, source=source,
                            sketch="auto", seed=idx, desc=desc))
                        reg.save()
                        results.append({"name": name, "kind": kind, "ok": True, "file": f"image/{out.name}", "meta": f"{info['from']} -> {info['to']}"})
                except Exception as e:
                    results.append({"name": name, "kind": kind, "ok": False, "error": str(e)[:300]})
            # auto-generate CSV + checklist if any succeeded
            csv_map = {}
            checklist_url = None
            if any(r["ok"] for r in results):
                try:
                    reg = assets_mod.Registry.load(_BATCH)
                    written = meta_mod.build_per_kind_csvs(_CFG, reg, _BATCH)
                    from .main import _write_upload_checklist
                    _write_upload_checklist(_BATCH, reg)
                    csv_map = {k: f"/files/{p.name}" for k, p in written.items()}
                    checklist_url = "/files/upload_checklist.txt"
                except Exception as e:
                    # CSV failure shouldn't hide batch results
                    results.append({"name": "_csv", "ok": False, "error": f"CSV build failed: {e}"})
            return {"total": len(files), "results": results, "csv": csv_map, "checklist_url": checklist_url}

        def _registry(self):
            reg = assets_mod.Registry.load(_BATCH)
            return {"batch": _BATCH.name,
                    "assets": [{"file": a.file, "kind": a.kind, "source": a.source,
                                "desc": a.desc, "is_ai": a.is_ai,
                                "sellable": a.sellable} for a in reg.assets]}

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
                    "checklist_url": "/files/upload_checklist.txt",
                    "descs": {a.file: (a.desc or "") for a in reg.assets}}
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
