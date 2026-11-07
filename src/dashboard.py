"""Dependency-free local dashboard for GridPulse evaluation artifacts."""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
NEM_PATH = ROOT / "data" / "processed" / "nem_pipeline_evaluation.json"
NEM_FALLBACK_PATH = ROOT / "data" / "processed" / "nem_baseline_evaluation.json"
WA_PATH = ROOT / "data" / "processed" / "wa_evaluation.json"


def _read_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dashboard_payload() -> dict[str, object]:
    return {
        "nem": _read_json(NEM_PATH) or _read_json(NEM_FALLBACK_PATH),
        "wa": _read_json(WA_PATH),
    }


def render_page(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, allow_nan=False).replace("</", "<\\/")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GridPulse Australia | Historical retrospective analysis</title>
<style>
:root{color-scheme:light;--ink:#17212b;--muted:#52606d;--blue:#1261a0;--teal:#007c83;--bg:#f4f7f9;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{background:#102a43;color:#fff;padding:28px max(24px,calc((100% - 1180px)/2))}main{max-width:1180px;margin:24px auto;padding:0 20px}
h1{margin:0 0 4px;font-size:clamp(1.7rem,3vw,2.4rem)}h2{margin-top:0;font-size:1.15rem}p{color:var(--muted)}
.status{display:inline-block;background:#d9f3f0;color:#075e54;border-radius:999px;padding:4px 11px;font-size:.84rem;margin-top:12px}
.controls,.card{background:var(--card);border:1px solid #d9e2ec;border-radius:10px;padding:18px;box-shadow:0 2px 6px #102a4310}
.controls{display:flex;gap:14px;flex-wrap:wrap;align-items:end;margin-bottom:18px}label{font-weight:600;display:grid;gap:5px}
select{font:inherit;padding:8px 10px;border:1px solid #9fb3c8;border-radius:6px;background:#fff;max-width:100%;min-width:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:14px 0}
.metric{font-size:1.45rem;font-weight:700;color:var(--blue)}.metric small{display:block;color:var(--muted);font-size:.78rem;font-weight:500}
table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{text-align:right;padding:8px;border-bottom:1px solid #e6edf3}th:first-child,td:first-child{text-align:left}
.chart{width:100%;height:330px;border:1px solid #d9e2ec;border-radius:6px;background:#fbfdff}.note{font-size:.9rem;border-left:4px solid var(--teal);padding-left:12px}
.empty{padding:22px;border:1px dashed #9fb3c8;background:#fbfdff;border-radius:8px}
@media(max-width:600px){main{padding:0 12px}.controls{display:block}.controls label{margin-bottom:10px}.controls select{width:100%}}
</style></head><body>
<header><h1>GridPulse Australia</h1><div>Evidence-first electricity-demand forecasting demonstrator</div>
<span class="status">Historical retrospective analysis · not live dispatch</span></header>
<main><section class="controls"><label>Market
<select id="market"><option value="NEM">NEM regional demand</option><option value="WA">WA SWIS/WEM native five-minute</option></select></label>
<label id="region-label">Region<select id="region"></select></label>
<label>Model<select id="model"></select></label><label>Fold<select id="fold"></select></label></section>
<section id="message" class="note"></section><section id="metrics" class="grid"></section>
<section class="card"><h2>Forecast and measured actuals</h2><svg id="chart" class="chart" role="img" aria-label="Forecast and actual demand chart"></svg></section>
<section class="card" style="margin-top:14px"><h2>Comparison and provenance</h2><div id="table"></div>
<p class="note">All values are generated from local evaluation artifacts. Source timestamps are retained verbatim; public issue-time availability and a universal UTC conversion are not asserted.</p></section>
<section class="card" style="margin-top:14px"><h2>Engineering status</h2>
<p>Validated local functions include NEM and WA ingestion, Python metrics, base-R comparison, MLflow tracking and PySpark parity. Delta Lake, sparklyr, Docker, Terraform, Databricks and GitHub execution are not represented as passed here.</p></section>
</main><script>
const DATA=__DATA__;
const $=id=>document.getElementById(id);
const esc=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function rows(){let m=$("market").value;let d=DATA[m==="NEM"?"nem":"wa"];return d&&d.results?d.results:[]}
function valueOrUnavailable(value){return Number.isFinite(Number(value))?Number(value).toFixed(2):"Unavailable"}
function setOptions(){let oldRegion=$("region").value,oldModel=$("model").value,oldFold=$("fold").value,r=rows();
let regions=[...new Set(r.map(x=>x.region||"WA_WEM_SWIS"))].sort(),region=regions.includes(oldRegion)?oldRegion:regions[0]||"";
$("region").innerHTML=regions.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("");$("region").value=region;
let regionRows=r.filter(x=>(x.region||"WA_WEM_SWIS")===region),models=[...new Set(regionRows.map(x=>x.model_id))].sort(),model=models.includes(oldModel)?oldModel:models[0]||"";
$("model").innerHTML=models.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("");$("model").value=model;
let folds=[...new Set(regionRows.filter(x=>x.model_id===model).map(x=>String(x.fold_id||x.origin_index)))].sort(),fold=oldFold==="aggregate"||folds.includes(oldFold)?oldFold:"aggregate";
$("fold").innerHTML="<option value='aggregate'>All qualifying folds</option>"+folds.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("");$("fold").value=fold;render()}
function render(){let region=$("region").value,model=$("model").value,r=rows().filter(x=>(x.region||"WA_WEM_SWIS")===region&&x.model_id===model),selected=$("fold").value;
let shown=selected==="aggregate"?r:r.filter(x=>String(x.fold_id||x.origin_index)===selected);
if(!r.length||!shown.length){$("message").textContent="No matching evaluation artifact is available for the selected market, region, model and fold."; $("metrics").innerHTML="";$("table").innerHTML="";$("chart").innerHTML="";return}
let points=DATA.nem&&DATA.nem.forecasts?DATA.nem.forecasts.filter(x=>x.region===region&&x.model_id===model&&(selected==="aggregate"||String(x.fold_id||x.origin_index)===selected)):[],x=shown[0];
$("message").textContent=`${x.market||"WA"} · ${selected==="aggregate"?"aggregate across "+shown.length+" folds":"selected fold "+selected} · retrospective source-order evaluation`;
let names=[["mae_mw","MAE (MW)"],["rmse_mw","RMSE (MW)"],["mape_percent","MAPE (%)"],["smape_percent","sMAPE (%)"],["mase","MASE"],["rmsse","RMSSE"],["bias_mw","Bias (MW)"]];
$("metrics").innerHTML=names.map(([k,n])=>{let valid=shown.map(v=>Number(v[k])).filter(Number.isFinite);let mean=valid.length?valid.reduce((a,v)=>a+v,0)/valid.length:null;return `<div class="card metric">${valueOrUnavailable(mean)}<small>${n} · fold mean (${valid.length}/${shown.length} valid)</small></div>`}).join("");
$("table").innerHTML="<table><thead><tr><th>Fold</th><th>MAE</th><th>RMSE</th><th>MAPE eligibility</th><th>Coverage</th></tr></thead><tbody>"+shown.map((v,i)=>`<tr><td>${esc(v.fold_id||i+1)}</td><td>${valueOrUnavailable(v.mae_mw)}</td><td>${valueOrUnavailable(v.rmse_mw)}</td><td>${v.mape_valid_count??"Unavailable"}/${v.matched_valid_count??"Unavailable"}</td><td>${v.matched_valid_count??"Unavailable"}/${v.planned_count??"Unavailable"}</td></tr>`).join("")+"</tbody></table>";
draw(shown,points,selected)}
function draw(r,points,selected){let s=$("chart"),w=900,h=300,p=32;
if(selected==="aggregate"&&$("market").value==="NEM")points=[];
if(points.length){let actual=points.map(x=>x.actual_mw),forecast=points.map(x=>x.forecast_mw),all=actual.concat(forecast),lo=Math.min(...all),hi=Math.max(...all)||1;
let y=v=>h-p-(v-lo)/(hi-lo||1)*(h-2*p),x=i=>p+i*(w-2*p)/Math.max(1,points.length-1),line=vals=>vals.map((v,i)=>(i?"L":"M")+x(i)+" "+y(v)).join(" ");
s.setAttribute("viewBox",`0 0 ${w} ${h}`);s.innerHTML=`<path d="${line(actual)}" fill="none" stroke="#1261a0" stroke-width="3"/><path d="${line(forecast)}" fill="none" stroke="#e07a5f" stroke-width="3" stroke-dasharray="7 5"/><text x="${p}" y="20" fill="#1261a0">Actual MW</text><text x="${p+110}" y="20" fill="#e07a5f">Forecast MW</text>`}
else{let a=r.map(x=>Number(x.mae_mw)).filter(Number.isFinite),b=r.map(x=>Number(x.rmse_mw)).filter(Number.isFinite),all=a.concat(b);
if(!all.length){s.innerHTML="";return}let lo=Math.min(...all),hi=Math.max(...all)||1,y=v=>h-p-(v-lo)/(hi-lo||1)*(h-2*p),x=i=>p+i*(w-2*p)/Math.max(1,r.length-1),line=vals=>vals.map((v,i)=>(i?"L":"M")+x(i)+" "+y(v)).join(" ");
s.setAttribute("viewBox",`0 0 ${w} ${h}`);let label=$("market").value==="WA"?"Fold-level MAE/RMSE (not actual versus forecast)":"Aggregate fold-level MAE/RMSE";s.innerHTML=`<path d="${line(a)}" fill="none" stroke="#1261a0" stroke-width="3"/><path d="${line(b)}" fill="none" stroke="#007c83" stroke-width="3" stroke-dasharray="7 5"/><text x="${p}" y="20" fill="#52606d">${label}</text>`}}
$("market").onchange=setOptions;$("region").onchange=setOptions;$("model").onchange=setOptions;$("fold").onchange=render;setOptions();
</script></body></html>""".replace("__DATA__", encoded)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path != "/":
            self.send_error(404)
            return
        body = render_page(dashboard_payload()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local GridPulse dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()
    print(f"GridPulse dashboard listening at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
