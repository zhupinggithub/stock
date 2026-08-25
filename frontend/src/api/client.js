export async function get(path){const r=await fetch(`/api${path}`);if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||`HTTP ${r.status}`)}return r.json()}
export const fmt=(v,d=2)=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d})
export const pct=v=>v==null?'—':`${(Number(v)*100).toFixed(2)}%`
