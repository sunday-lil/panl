"""panl 桌面版界面（单文件 HTML，无外部依赖）。

设计取向：深色玻璃拟态 + 渐变强调色 + 轻动效，左侧导航 + 右侧结果流。
所有图标用内联 SVG，字体用系统栈，页面离线可用。
"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>panl · 网盘直链</title>
<style>
:root{
  --bg:#080b11; --bg2:#0c1018; --panel:#111722; --panel2:#151c29; --line:rgba(255,255,255,.07);
  --text:#e8eef8; --muted:#8797ad; --dim:#5d6b80;
  --accent:#6c7bff; --accent2:#22d3ee; --ok:#34d399; --warn:#fbbf24; --err:#f87171;
  --radius:16px; --shadow:0 18px 46px rgba(0,0,0,.45);
}
*{box-sizing:border-box}
::selection{background:rgba(108,123,255,.35)}
html,body{height:100%}
body{
  margin:0; color:var(--text); font:14px/1.6 "Segoe UI Variable","Segoe UI",-apple-system,"Microsoft YaHei",system-ui,sans-serif;
  background:
    radial-gradient(1100px 620px at 12% -8%, rgba(108,123,255,.20), transparent 60%),
    radial-gradient(900px 520px at 92% 8%, rgba(34,211,238,.13), transparent 55%),
    linear-gradient(180deg,var(--bg),var(--bg2) 60%,#070a0f);
  min-height:100%; overflow:hidden;
}
.app{display:grid; grid-template-columns:248px 1fr; height:100vh}

/* ---------- 侧栏 ---------- */
.side{
  border-right:1px solid var(--line); padding:20px 14px; display:flex; flex-direction:column; gap:18px;
  background:linear-gradient(180deg, rgba(255,255,255,.03), transparent 40%);
}
.brand{display:flex; align-items:center; gap:11px; padding:4px 6px 0}
.mark{
  width:38px;height:38px;border-radius:12px;display:grid;place-items:center;
  background:linear-gradient(135deg,#6c7bff,#22d3ee); box-shadow:0 8px 24px rgba(108,123,255,.35);
  font-weight:800; font-size:17px; color:#08101c;
}
.brand h1{font-size:15px;margin:0;letter-spacing:.2px}
.brand p{margin:1px 0 0;font-size:11.5px;color:var(--dim)}
.nav{display:flex;flex-direction:column;gap:4px}
.nav a{
  display:flex;align-items:center;gap:10px;padding:9px 11px;border-radius:11px;color:var(--muted);
  text-decoration:none;font-size:13.5px;transition:.18s; cursor:pointer;
}
.nav a:hover{background:rgba(255,255,255,.045); color:var(--text)}
.nav a.on{background:linear-gradient(90deg, rgba(108,123,255,.18), rgba(34,211,238,.06)); color:#fff;
  box-shadow:inset 0 0 0 1px rgba(108,123,255,.28)}
.nav .badge{margin-left:auto;font-size:11px;color:var(--dim)}
.sect{font-size:11px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase;padding:0 10px}
.hist{display:flex;flex-direction:column;gap:2px;overflow:auto;max-height:34vh}
.hist .h{
  display:flex;gap:8px;align-items:center;padding:7px 10px;border-radius:10px;cursor:pointer;
  font-size:12.5px;color:var(--muted);transition:.15s; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.hist .h:hover{background:rgba(255,255,255,.045);color:var(--text)}
.hist .h i{width:6px;height:6px;border-radius:50%;background:var(--accent);flex:none;opacity:.8}
.side .foot{margin-top:auto;font-size:11.5px;color:var(--dim);padding:0 8px;line-height:1.9}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--ok);margin-right:6px;
  box-shadow:0 0 0 3px rgba(52,211,153,.15)}

/* ---------- 主区 ---------- */
.main{display:flex;flex-direction:column;min-width:0}
.top{
  display:flex;align-items:center;gap:14px;padding:16px 26px;border-bottom:1px solid var(--line);
  backdrop-filter:blur(8px); background:rgba(9,13,19,.55); position:sticky; top:0; z-index:5;
}
.top h2{margin:0;font-size:15px;font-weight:600;letter-spacing:.2px}
.pill{
  margin-left:auto;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);
  border:1px solid var(--line);padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.02)
}
.scroll{overflow:auto;padding:26px; display:flex; flex-direction:column; gap:18px; height:100%}

.card{
  background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.012));
  border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow);
}
.pad{padding:20px}

/* 输入卡 */
.compose{display:flex;flex-direction:column;gap:14px}
.compose .head{display:flex;align-items:center;gap:10px}
.compose .head .t{font-size:13px;color:var(--muted)}
.drop{
  position:relative;border:1px dashed rgba(255,255,255,.14);border-radius:14px;background:rgba(0,0,0,.22);
  transition:.2s;
}
.drop.hot{border-color:var(--accent);background:rgba(108,123,255,.10)}
textarea{
  width:100%;min-height:132px;resize:vertical;border:0;background:transparent;color:var(--text);
  padding:14px 16px;font:13px/1.75 ui-monospace,"Cascadia Code",Consolas,monospace;outline:none;border-radius:14px;
}
textarea::placeholder{color:#4c5a6e}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.field{
  display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.04);border:1px solid var(--line);
  border-radius:11px;padding:8px 12px;transition:.15s;min-width:190px;
}
.field:focus-within{border-color:rgba(108,123,255,.6); box-shadow:0 0 0 3px rgba(108,123,255,.12)}
.field.grow{flex:1;min-width:250px}
.field input{border:0;background:transparent;color:var(--text);outline:none;font:13px/1 inherit;width:100%;min-width:0}
.field svg{flex:none;opacity:.6}
.switch{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);cursor:pointer;user-select:none}
.switch input{appearance:none;width:34px;height:19px;border-radius:999px;background:#26303f;position:relative;transition:.2s;cursor:pointer}
.switch input:checked{background:linear-gradient(90deg,var(--accent),var(--accent2))}
.switch input::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:#fff;transition:.2s}
.switch input:checked::after{transform:translateX(15px)}
.btn{
  display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:rgba(255,255,255,.04);
  color:var(--text);padding:10px 16px;border-radius:11px;font:13.5px/1 inherit;cursor:pointer;transition:.18s;
}
.btn:hover{border-color:rgba(255,255,255,.2); transform:translateY(-1px)}
.btn.primary{
  border:0;background:linear-gradient(135deg,var(--accent),#8b5cf6 55%,var(--accent2));color:#fff;font-weight:600;
  box-shadow:0 10px 26px rgba(108,123,255,.35);
}
.btn.primary:disabled{opacity:.6;cursor:progress;transform:none}
.btn.ghost{background:transparent}
.btn.primary .kbd{background:rgba(255,255,255,.2);border-color:transparent;color:#fff;opacity:.9}
.btn.mini{padding:6px 10px;font-size:12px;border-radius:9px}
.kbd{font:11px ui-monospace,Consolas,monospace;color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:1px 6px}

/* 结果卡 */
.res{display:flex;flex-direction:column;gap:14px}
.item{
  border:1px solid var(--line);border-radius:15px;overflow:hidden;
  background:linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.015));
  animation:in .28s cubic-bezier(.2,.7,.3,1) both;
}
@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.ihead{display:flex;align-items:center;gap:11px;padding:13px 16px;border-bottom:1px solid var(--line);background:rgba(0,0,0,.18)}
.plat{
  display:inline-flex;align-items:center;gap:7px;font-size:12px;padding:4px 10px;border-radius:999px;
  background:rgba(108,123,255,.14);color:#bcc8ff;border:1px solid rgba(108,123,255,.28)
}
.ihead .title{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:46%}
.ihead .count{font-size:12px;color:var(--muted)}
.ihead .acts{margin-left:auto;display:flex;gap:7px}
.files{padding:6px 16px 14px}
.f{
  display:grid;grid-template-columns:1fr 88px auto auto auto;gap:9px;align-items:center;
  padding:9px 0;border-top:1px solid rgba(255,255,255,.05);font-size:13px;
}
.f:first-child{border-top:0}
.f:hover{background:rgba(255,255,255,.028);border-radius:9px}
.f{padding-left:8px;padding-right:8px;margin:0 -8px}
.f .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.f .sz{color:var(--muted);font-size:12px;text-align:right;font-variant-numeric:tabular-nums}
.link{
  display:inline-flex;align-items:center;gap:6px;color:var(--ok);text-decoration:none;font-size:12.5px;
  padding:4px 9px;border-radius:8px;border:1px solid rgba(52,211,153,.28);background:rgba(52,211,153,.08)
}
.link:hover{background:rgba(52,211,153,.16)}
.miss{color:var(--warn);font-size:12px;display:inline-flex;align-items:center;gap:6px}
.gbtn{color:#9df0d0;border-color:rgba(52,211,153,.3);background:rgba(52,211,153,.08)}
.gbtn:hover{background:rgba(52,211,153,.16)}
.gbtn[disabled]{opacity:.5}
.note{margin:10px 16px 14px;padding:10px 12px;border-radius:10px;font-size:12.5px;
  background:rgba(251,191,36,.09);border:1px solid rgba(251,191,36,.22);color:#f3d9a4}
.err{margin:0;padding:14px 16px;font-size:13px;background:rgba(248,113,113,.08);border-top:1px solid rgba(248,113,113,.2);color:#ffc9c9}
.err code{background:rgba(0,0,0,.3);padding:2px 6px;border-radius:6px;font-size:12px}

/* 空态 / 骨架 */
.empty{display:flex;flex-direction:column;align-items:center;gap:14px;padding:56px 20px;color:var(--dim);text-align:center}
.empty svg{opacity:.5}
.empty b{color:var(--muted);font-weight:600;font-size:14px}
.skel{height:74px;border-radius:14px;background:linear-gradient(100deg,#141b26 30%,#1b2431 45%,#141b26 60%);
  background-size:220% 100%;animation:sh 1.2s infinite linear}
@keyframes sh{to{background-position:-120% 0}}
.chips{display:flex;gap:7px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);
  border:1px solid var(--line);padding:4px 10px;border-radius:999px}
.chip b{color:var(--text);font-weight:600}
.chip .needs{color:var(--warn)}

/* 传输面板（接 grabdown） */
.grab{
  position:fixed;right:22px;bottom:22px;width:372px;z-index:40;
  border:1px solid var(--line);border-radius:15px;overflow:hidden;
  background:rgba(18,24,35,.96);backdrop-filter:blur(14px);box-shadow:0 20px 50px rgba(0,0,0,.55);
  animation:in .25s cubic-bezier(.2,.7,.3,1) both;
}
.grab .gh{display:flex;align-items:center;gap:9px;padding:11px 13px;border-bottom:1px solid var(--line);
  background:rgba(255,255,255,.03);cursor:pointer}
.grab .gh .gg{width:22px;height:22px;border-radius:7px;display:grid;place-items:center;
  background:linear-gradient(135deg,#34d399,#22d3ee);color:#05130f;font-weight:800;font-size:12px}
.grab .gh b{font-size:12.5px}
.grab .gh .off{margin-left:auto;font-size:11px;color:var(--dim)}
.grab .gbody{max-height:260px;overflow:auto;padding:4px 0}
.grab .gr{padding:9px 13px;border-bottom:1px solid rgba(255,255,255,.05)}
.grab .gr:last-child{border-bottom:0}
.grab .gt{display:flex;align-items:center;gap:8px;font-size:12px}
.grab .gt .st{font-size:10.5px;padding:1px 7px;border-radius:999px;background:rgba(255,255,255,.07);color:var(--muted)}
.grab .gt .st.done{background:rgba(52,211,153,.16);color:#9df0d0}
.grab .gt .st.error{background:rgba(248,113,113,.16);color:#ffc9c9}
.grab .gt .st.running{background:rgba(108,123,255,.2);color:#bcc8ff}
.grab .gt .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grab .gt .sz{color:var(--dim);font-size:11px;white-space:nowrap}
.gbar{height:4px;border-radius:999px;background:rgba(255,255,255,.08);margin-top:6px;overflow:hidden}
.gbar i{display:block;height:100%;background:linear-gradient(90deg,#34d399,#22d3ee);width:0;transition:width .25s}
.grab.min .gbody{display:none}

/* toast */
.toast{
  position:fixed;left:50%;bottom:28px;transform:translate(-50%,16px);opacity:0;pointer-events:none;
  background:rgba(20,27,39,.96);border:1px solid rgba(255,255,255,.12);border-radius:12px;
  padding:10px 18px;font-size:13px;box-shadow:0 16px 40px rgba(0,0,0,.5);transition:.22s;z-index:50
}
.toast.on{opacity:1;transform:translate(-50%,0)}
.hide{display:none!important}
@media (max-width:900px){
  .app{grid-template-columns:1fr} .side{display:none}
  .scroll{padding:16px}
}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">
      <div class="mark">p</div>
      <div><h1>panl</h1><p>网盘直链提取</p></div>
    </div>

    <nav class="nav">
      <a class="on" data-view="resolve">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M4 12h10M4 17h7"/></svg>
        解析 <span class="badge" id="navCount"></span>
      </a>
      <a data-view="history">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>
        历史
      </a>
      <a data-view="about">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>
        关于
      </a>
    </nav>

    <div class="sect">最近解析</div>
    <div class="hist" id="hist"></div>

    <div class="foot">
      <div><span class="dot"></span>本地服务 <span id="ver">—</span></div>
      <div style="margin-top:6px">直链由网盘直发，页面不中转。</div>
    </div>
  </aside>

  <main class="main">
    <div class="top">
      <h2 id="viewTitle">解析分享链接</h2>
      <div class="pill" id="pill"><span class="dot"></span>就绪</div>
    </div>

    <div class="scroll" id="scroll">
      <!-- 解析视图 -->
      <section id="view-resolve" style="display:flex;flex-direction:column;gap:16px">
        <div class="card pad compose">
          <div class="head">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.8"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
            <span class="t">粘贴分享链接，每行一个（最多 10 条）</span>
          </div>
          <div class="drop" id="drop">
            <textarea id="urls" spellcheck="false" placeholder="https://www.alipan.com/s/xxxxxx
https://pan.baidu.com/s/1xxxxxx?pwd=1234
https://pan.quark.cn/s/xxxxxx"></textarea>
          </div>
          <div class="row">
            <label class="field grow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>
              <input id="pwd" placeholder="提取码（可选）" />
            </label>
            <label class="field" style="min-width:120px">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
              <input id="max" type="number" min="20" max="500" value="200" />
            </label>
            <label class="switch"><input type="checkbox" id="rec" checked />展开子目录</label>
            <div style="margin-left:auto" class="row">
              <button class="btn ghost" id="clear">清空</button>
              <button class="btn primary" id="go">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h13m0 0l-5-5m5 5l-5 5"/></svg>
                开始解析 <span class="kbd">Ctrl ↵</span>
              </button>
            </div>
          </div>
          <div class="chips" id="chips"></div>
        </div>

        <div class="res" id="res">
          <div class="card empty">
            <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M4 7a2 2 0 012-2h5l2 2h5a2 2 0 012 2v3H4V7z"/><path d="M4 12h16l-1.6 6.2A2 2 0 0116.5 20h-9a2 2 0 01-1.9-1.8L4 12z"/></svg>
            <div><b>还没有结果</b></div>
            <div style="font-size:12.5px;max-width:420px">粘贴链接后点「开始解析」，或直接把链接拖进来。直链大多要带 Referer，卡片里给了现成的 curl / aria2 命令。</div>
          </div>
        </div>
      </section>

      <!-- 历史视图 -->
      <section id="view-history" class="hide"></section>

      <!-- 关于 -->
      <section id="view-about" class="hide">
        <div class="card pad">
          <h3 style="margin:0 0 10px;font-size:15px">panl · 网盘分享直链提取器</h3>
          <p style="color:var(--muted);margin:0 0 14px">
            解析 → 列目录 → 取直链，全部在本机完成；不经过任何第三方服务器。
            支持阿里云盘 / 百度网盘 / 123 云盘 / 夸克 / UC / 蓝奏 / 天翼 / 115 / 微云 / 迅雷。
          </p>
          <div class="chips" id="chips2"></div>
          <p style="color:var(--dim);font-size:12.5px;margin:16px 0 0">
            需要登录的网盘：命令行执行 <code style="background:rgba(0,0,0,.35);padding:2px 6px;border-radius:6px">python -m panl cookie set baidu BDUSS=…</code>，刷新本页生效。
            直链有时效（阿里约 15 分钟），过期重新解析即可。
          </p>
        </div>
      </section>
    </div>
  </main>
</div>

<div class="grab hide" id="grab">
  <div class="gh" id="grabHead">
    <span class="gg">g</span>
    <b>传输 · grabdown</b>
    <span class="off" id="grabState">检测中…</span>
  </div>
  <div class="gbody" id="grabBody"></div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const HKEY = "panl.history.v1";
let results = [], hist = [];

/* ---------- 基础 ---------- */
function toast(msg){
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove("on"), 1700);
}
async function copy(text, label){
  try { await navigator.clipboard.writeText(text); toast((label||"已复制") + " ✓"); }
  catch(e){ toast("复制失败，请手动选中"); }
}
function pill(text, kind){
  const p = $("#pill");
  p.innerHTML = `<span class="dot" style="background:${kind==='busy'?'#fbbf24':kind==='err'?'#f87171':'#34d399'}"></span>${esc(text)}`;
}
function curl(f){
  const hs = Object.entries(f.headers||{}).map(([k,v]) => `-H '${k}: ${v.replace(/'/g,"'\\''")}'`).join(" ");
  return `curl -L -C - ${hs} -o '${(f.name||"file").replace(/'/g,"'\\''")}' '${f.url}'`;
}
function aria(f){
  const hs = Object.entries(f.headers||{}).map(([k,v]) => `--header='${k}: ${v.replace(/'/g,"'\\''")}'`).join(" ");
  return `aria2c -c -x16 -s16 -k1M ${hs} -o '${(f.name||"file").replace(/'/g,"'\\''")}' '${f.url}'`;
}

/* ---------- 视图切换 ---------- */
function view(name){
  $$(".nav a").forEach(a => a.classList.toggle("on", a.dataset.view === name));
  ["resolve","history","about"].forEach(v => {
    const el = $("#view-" + v); if (el) el.classList.toggle("hide", v !== name);
  });
  $("#viewTitle").textContent = {resolve:"解析分享链接", history:"解析历史", about:"关于"}[name] || "";
  if (name === "history") renderHistory();
}

/* ---------- 历史 ---------- */
function loadHist(){ try { hist = JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch { hist = []; } }
function saveHist(){
  hist = hist.slice(0, 20);
  localStorage.setItem(HKEY, JSON.stringify(hist));
  renderHist();
}
function renderHist(){
  const box = $("#hist");
  if (!hist.length){ box.innerHTML = `<div class="h" style="color:var(--dim);cursor:default">暂无记录</div>`; return; }
  box.innerHTML = hist.slice(0,8).map((h,i) =>
    `<div class="h" data-h="${i}" title="${esc(h.url)}"><i></i>${esc(h.title || h.url)}</div>`).join("");
  $$("#hist .h[data-h]").forEach(el => el.onclick = () => {
    $("#urls").value = hist[Number(el.dataset.h)].url;
    view("resolve"); $("#go").click();
  });
}
function pushHist(r){
  if (!r.ok) return;
  hist = [{url:r.url, title:(r.title||"").slice(0,60), provider:r.provider, ts:Date.now()},
          ...hist.filter(h => h.url !== r.url)].slice(0,20);
  saveHist();
}
function renderHistory(){
  const box = $("#view-history");
  if (!hist.length){ box.innerHTML = `<div class="card empty"><b>还没有历史</b><div style="font-size:12.5px">解析成功后会自动记录在本机（localStorage，不上传）。</div></div>`; return; }
  box.innerHTML = `<div class="card"><div class="files">` + hist.map(h => `
    <div class="f" style="grid-template-columns:1fr auto auto">
      <div class="nm">${esc(h.title || h.url)}<div style="color:var(--dim);font-size:11.5px">${esc(h.url)}</div></div>
      <div class="sz">${esc(h.provider||"")}</div>
      <button class="btn mini" data-again="${esc(h.url)}">再解析</button>
    </div>`).join("") + `</div></div>`;
  $$("[data-again]").forEach(b => b.onclick = () => {
    $("#urls").value = b.dataset.again; view("resolve"); $("#go").click();
  });
}

/* ---------- 渲染结果 ---------- */
function fileRow(f, ri, fi){
  const ok = !!f.url;
  return `<div class="f">
    <div class="nm" title="${esc(f.name)}">${esc(f.name)}</div>
    <div class="sz">${esc(f.size_h || "")}</div>
    ${ok ? `<a class="link" href="${esc(f.url)}" target="_blank" rel="noreferrer">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 4v11m0 0l-4-4m4 4l4-4"/><path d="M5 19h14"/></svg>直链</a>`
      : `<span class="miss">无直链</span>`}
    <div style="display:flex;gap:6px">${ok ? `<button class="btn mini" data-copy="${ri}-${fi}">复制</button>
      <button class="btn mini gbtn" data-grab="${ri}-${fi}" title="交给 grabdown 多线程下载">下载</button>` : ""}</div>
  </div>`;
}

function render(list){
  const box = $("#res");
  if (!list.length){ box.innerHTML = `<div class="card empty"><b>没有结果</b></div>`; return; }
  box.innerHTML = list.map((r, i) => {
    if (!r.ok){
      return `<div class="item">
        <div class="ihead">
          <span class="plat">${esc(r.label || r.provider || "错误")}</span>
          <span class="title" style="font-weight:400;color:var(--muted)">${esc(r.url)}</span>
        </div>
        <div class="err"><b>${esc(r.code)}</b> · ${esc(r.message)}
          ${r.detail ? `<div style="color:#d9a6a6;margin-top:6px"><code>${esc(r.detail)}</code></div>` : ""}
          ${r.need_password ? `<div style="margin-top:6px">补上提取码再点一次「开始解析」</div>` : ""}
        </div>
      </div>`;
    }
    const files = (r.files||[]).map((f, j) => fileRow(f, i, j)).join("");
    return `<div class="item">
      <div class="ihead">
        <span class="plat">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="6"/></svg>
          ${esc(r.label)}
        </span>
        <span class="title" title="${esc(r.title||'')}">${esc(r.title || r.share_id || "")}</span>
        <span class="count">${r.resolved_count}/${r.file_count}</span>
        <div class="acts">
          <button class="btn mini" data-exp="aria2" data-i="${i}">aria2</button>
          <button class="btn mini" data-exp="json" data-i="${i}">JSON</button>
        </div>
      </div>
      ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}
      <div class="files">${files || `<div class="empty" style="padding:22px">空目录</div>`}</div>
    </div>`;
  }).join("");

  $$("[data-copy]").forEach(b => b.onclick = () => {
    const [ri, fi] = b.dataset.copy.split("-").map(Number);
    copy(curl(results[ri].files[fi]), "curl 已复制");
  });
  $$("[data-grab]").forEach(b => b.onclick = () => {
    const [ri, fi] = b.dataset.grab.split("-").map(Number);
    grabDownload(results[ri].files[fi], b);
  });
  $$("[data-exp]").forEach(b => b.onclick = async () => {
    const r = results[Number(b.dataset.i)];
    try {
      const resp = await fetch("/api/export", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({fmt: b.dataset.exp, provider:r.provider, title:r.title, files:r.files})
      }).then(x => x.json());
      if (resp.ok) copy(resp.text, b.dataset.exp + " 已复制"); else toast("导出失败");
    } catch(e){ toast("导出失败: " + e.message); }
  });
}

/* ---------- 解析 ---------- */
async function resolveNow(){
  const urls = $("#urls").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (!urls.length){ toast("先粘贴链接"); $("#urls").focus(); return; }
  if (urls.length > 10){ toast("一次最多 10 条"); return; }
  const btn = $("#go"); btn.disabled = true;
  pill("解析中…", "busy");
  $("#res").innerHTML = Array.from({length: Math.min(urls.length, 3)}, () =>
    `<div class="skel"></div>`).join("");
  const t0 = Date.now();
  try {
    const data = await fetch("/api/resolve", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({urls, pwd: $("#pwd").value.trim(), recursive: $("#rec").checked,
                            max: Number($("#max").value) || 200})
    }).then(r => r.json());
    if (!data.ok){ $("#res").innerHTML = `<div class="card"><div class="err">${esc(data.message||"请求失败")}</div></div>`; return; }
    results = data.results || [];
    results.forEach(pushHist);
    render(results);
    const ok = results.filter(r => r.ok).length;
    const files = results.reduce((n, r) => n + (r.ok ? r.resolved_count : 0), 0);
    $("#navCount").textContent = results.length ? String(results.length) : "";
    pill(`完成 ${((Date.now()-t0)/1000).toFixed(1)}s · ${ok}/${results.length} 条 · ${files} 个直链`);
  } catch(e){
    $("#res").innerHTML = `<div class="card"><div class="err">本地服务连不上：${esc(e.message)}</div></div>`;
    pill("服务异常", "err");
  } finally { btn.disabled = false; }
}

/* ---------- 交互绑定 ---------- */
$("#go").onclick = resolveNow;
$("#clear").onclick = () => { $("#urls").value = ""; results = []; $("#res").innerHTML =
  `<div class="card empty"><b>已清空</b></div>`; $("#navCount").textContent = ""; pill("就绪"); };
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter"){ e.preventDefault(); resolveNow(); }
});
$$(".nav a").forEach(a => a.onclick = () => view(a.dataset.view));

/* 拖拽文本进输入区 */
const drop = $("#drop");
["dragenter","dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hot"); }));
["dragleave","drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", e => {
  const txt = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain");
  if (txt){ $("#urls").value = ($("#urls").value.trim() + "\n" + txt).trim(); toast("已填入链接"); }
});

/* ---------- grabdown：点「下载」= 多线程下载到本地 ---------- */
let grabOnline = false, grabJobs = [], grabES = null, grabMin = false;

function fmtSize(n){
  if (!n) return "0B";
  const u = ["B","KB","MB","GB","TB"]; let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1){ v /= 1024; i++; }
  return v.toFixed(v >= 100 ? 0 : 1) + u[i];
}
function grabStateText(){
  $("#grabState").textContent = grabOnline
    ? (grabJobs.filter(j => j.state === "running" || j.state === "queued").length || "") + ""
    : "agent 未启动";
  if (grabOnline) {
    const n = grabJobs.filter(j => j.state === "running" || j.state === "queued").length;
    $("#grabState").textContent = n ? n + " 个进行中" : "空闲";
  }
}
function grabRow(j){
  const pct = j.state === "done" ? 100 : (j.percent || 0);
  const size = j.total_bytes ? `${fmtSize(j.done_bytes)} / ${fmtSize(j.total_bytes)}` : "";
  const label = {queued:"排队", running:"下载中", done:"完成", error:"失败", cancelled:"已取消"}[j.state] || j.state;
  const name = (j.title || (j.url || "").split("/").pop() || "文件");
  return `<div class="gr">
    <div class="gt">
      <span class="st ${esc(j.state)}">${esc(label)}</span>
      <span class="nm" title="${esc(j.out_path || j.url)}">${esc(name)}</span>
      <span class="sz">${esc(size)}</span>
    </div>
    <div class="gbar"><i style="width:${pct}%"></i></div>
    ${j.error ? `<div style="color:#ffb4b4;font-size:11px;margin-top:4px">${esc(j.error)}</div>` : ""}
  </div>`;
}
function renderGrab(){
  const box = $("#grab"), body = $("#grabBody");
  const has = grabJobs.length > 0;
  box.classList.toggle("hide", !has && grabOnline);
  if (!has && !grabOnline) box.classList.add("hide");
  body.innerHTML = has
    ? grabJobs.slice(0, 8).map(grabRow).join("")
    : `<div class="gr" style="color:var(--dim);font-size:12px">没有传输任务。点文件行的「下载」交给 grabdown。</div>`;
  grabStateText();
}
function applyJobs(list){
  grabJobs = (list || []).slice().sort((a,b) => (b.created||0)-(a.created||0));
  const box = $("#grab");
  if (grabJobs.length) box.classList.remove("hide");
  renderGrab();
}
function openGrabStream(){
  if (grabES) return;
  try {
    grabES = new EventSource("/api/grab/stream");
    grabES.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.type === "snapshot"){ grabOnline = !!m.online; applyJobs(m.jobs); }
      else if (m.type === "jobs"){ grabOnline = true; applyJobs(m.jobs); }
      else if (m.type === "offline"){ grabOnline = false; grabStateText(); }
    };
    grabES.onerror = () => { /* EventSource 自己会重连 */ };
  } catch(e){ /* ignore */ }
}
async function grabPing(){
  try {
    const r = await fetch("/api/grab/ping").then(x => x.json());
    grabOnline = !!r.ok;
    $("#grabState").textContent = grabOnline ? "空闲" : "agent 未启动";
    if (!r.ok) $("#grab").classList.add("hide");
  } catch { grabOnline = false; }
  return grabOnline;
}
async function grabDownload(f, btn){
  if (!f || !f.url) { toast("这个文件没有直链"); return; }
  const old = btn ? btn.textContent : "";
  if (btn){ btn.disabled = true; btn.textContent = "提交…"; }
  try {
    const r = await fetch("/api/grab", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: f.url, headers: f.headers || {}, name: f.name, quality: "best"})
    }).then(x => x.json());
    if (!r.ok){
      toast(r.hint || r.message || "提交失败");
      grabOnline = false;
      $("#grabState").textContent = "agent 未启动";
      return;
    }
    grabOnline = true;
    $("#grab").classList.remove("hide");
    toast("已交给 grabdown 下载");
    openGrabStream();
  } catch(e){
    toast("提交失败：" + e.message);
  } finally {
    if (btn){ btn.disabled = false; btn.textContent = old || "下载"; }
  }
}
$("#grabHead").onclick = () => {
  const box = $("#grab");
  box.classList.toggle("min");
};

/* ---------- 启动 ---------- */
fetch("/healthz").then(r => r.json()).then(d => { $("#ver").textContent = "v" + d.version; }).catch(()=>{});
fetch("/api/providers").then(r => r.json()).then(d => {
  const html = d.providers.map(p =>
    `<span class="chip"><b>${esc(p.label)}</b> ${p.cookie ? `<span class="needs">需 cookie</span>` : "匿名"}</span>`).join("");
  $("#chips").innerHTML = html; $("#chips2").innerHTML = html;
}).catch(()=>{});
loadHist(); renderHist();
grabPing();
</script>
</body>
</html>
"""
