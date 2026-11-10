"use strict";
/* Estoque Maxx Auto Ar - interface (JS puro, sem build). */

const S = {
  user: null, setupNeeded: false, setupHere: false, minDefault: 2,
  tab: "stock", cats: [], products: [], summary: null, moves: [],
  low: [], q: "", cat: 0, loaded: false,
};
const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app"), sheetRoot = $("#sheet-root");

const ICON = {
  box: '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  scan: '<path d="M4 8V5a1 1 0 011-1h3M16 4h3a1 1 0 011 1v3M20 16v3a1 1 0 01-1 1h-3M8 20H5a1 1 0 01-1-1v-3M7 12h10"/>',
  alert: '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5M12 18.5v.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
};
const svg = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n]}</svg>`;

/* ---------------------------------------------------------------- util */
let toastTimer;
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = ""), 2600);
}
async function api(path, opts = {}) {
  const o = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
  let r;
  try { r = await fetch("/api" + path, o); } catch { throw new Error("Sem conexão com o servidor."); }
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && S.user) { S.user = null; render(); }
  if (!r.ok) throw Object.assign(new Error(data.error || "Erro inesperado."), { status: r.status });
  return data;
}
const fmtDate = (s) => { const [d, t] = s.split(" "); const [, m, dd] = d.split("-"); return `${dd}/${m} ${t.slice(0, 5)}`; };
function beep() {
  try { const c = new (window.AudioContext || window.webkitAudioContext)(), o = c.createOscillator(); o.frequency.value = 880; o.connect(c.destination); o.start(); setTimeout(() => { o.stop(); c.close(); }, 110); } catch {}
  if (navigator.vibrate) navigator.vibrate(60);
}
const lowCount = () => (S.summary ? S.summary.low : 0);

/* ---------------------------------------------------------------- data */
const PAGE_SIZE = 200;
let productsRequest = 0;
/* Carrega a lista da aba Estoque (busca e categoria atuais), de página em página. Retorna false
   quando uma busca mais nova começou antes desta terminar: a resposta antiga é descartada. */
async function loadProducts(more = false) {
  const req = ++productsRequest;
  const qs = new URLSearchParams({ limit: PAGE_SIZE + 1, offset: more ? S.products.length : 0 });
  if (S.q) qs.set("q", S.q);
  if (S.cat) qs.set("category", S.cat);
  const page = await api("/products?" + qs);
  if (req !== productsRequest) return false;
  S.hasMore = page.length > PAGE_SIZE;
  S.products = (more ? S.products : []).concat(page.slice(0, PAGE_SIZE));
  return true;
}
async function loadAll() {
  const [, summary, cats] = await Promise.all([loadProducts(), api("/summary"), api("/categories")]);
  S.summary = summary; S.cats = cats; S.loaded = true;
}
/* Busca e filtro de categoria só mudam a lista: resumo e categorias continuam valendo. */
async function reloadProducts() {
  try { if (!(await loadProducts())) return false; } catch (e) { toast(e.message, true); }
  render();
  return true;
}
/* Dados proprios de cada aba (independentes da busca/filtro da aba Estoque). */
async function loadTabData() {
  if (S.tab === "history") S.moves = await api("/movements?limit=100");
  if (S.tab === "alerts") S.low = await api("/products?low=1");
}
async function refresh() { try { await loadAll(); await loadTabData(); } catch (e) { toast(e.message, true); } render(); }

/* ---------------------------------------------------------------- views */
function authView() {
  if (S.setupNeeded && !S.setupHere) return setupElsewhereView();
  const setup = S.setupNeeded;
  app.innerHTML = `<div class="login">
    <div class="logo"><img src="/static/icon.svg" alt=""><h1>Maxx Auto Ar<small>Controle de estoque</small></h1></div>
    <form id="auth" class="card">
      <div id="autherr"></div>
      ${setup ? `<div class="info">Primeiro acesso: crie o usuário do dono da oficina.</div>
      <label class="f"><span>Seu nome</span><input name="name" required autocomplete="name"></label>` : ""}
      <label class="f"><span>Usuário</span><input name="username" required autocapitalize="none" autocomplete="username"></label>
      <label class="f"><span>Senha</span><input name="password" type="password" required ${setup ? 'minlength="8" placeholder="Mínimo de 8 caracteres"' : ""} autocomplete="${setup ? "new-password" : "current-password"}"></label>
      <button class="btn block">${setup ? "Criar e entrar" : "Entrar"}</button>
    </form></div>`;
  $("#auth").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try { await api(setup ? "/setup" : "/login", { method: "POST", body }); await boot(); }
    catch (er) { $("#autherr").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
  };
}

function setupElsewhereView() {
  app.innerHTML = `<div class="login">
    <div class="logo"><img src="/static/icon.svg" alt=""><h1>Maxx Auto Ar<small>Controle de estoque</small></h1></div>
    <div class="info">O sistema ainda não foi configurado. Faça o primeiro acesso no computador da oficina,
      em <b>https://localhost:8443</b>, para criar o usuário do dono. Depois é só entrar por aqui.</div></div>`;
}

function shell(inner) {
  const tabs = [["stock", "box", "Estoque"], ["alerts", "alert", "Alertas"], ["scan", "scan", "Escanear"], ["history", "clock", "Histórico"], ["more", "menu", "Mais"]];
  const order = ["stock", "alerts", "scan", "history", "more"];
  const nav = order.map((k) => { const [, ic, label] = tabs.find((t) => t[0] === k);
    const cur = S.tab === k ? ' aria-current="page"' : "";
    if (k === "scan") return `<button class="scan" data-tab="scan"${cur}><span class="disc">${svg(ic)}</span><b>${label}</b></button>`;
    const dot = k === "alerts" && lowCount() ? `<span class="dot">${lowCount()}</span>` : "";
    return `<button data-tab="${k}"${cur}>${svg(ic)}${label}${dot}</button>`; }).join("");
  app.innerHTML = `<div class="shell">
    <header class="top"><div class="brand"><img src="/static/icon.svg" alt=""><div>Maxx Auto Ar<small>Estoque</small></div></div>
      <div class="who">${esc(S.user.name)}</div></header>
    <nav class="tabs" aria-label="Seções">${nav}</nav>
    <main><div class="wrap">${inner}</div></main></div>`;
}

function itemRow(p) {
  const cls = p.qty === 0 ? "zero" : p.low ? "low" : "";
  const meta = [p.code, p.brand].filter(Boolean).join(" · ");
  return `<button class="item ${cls}" data-open="${p.id}">
    <div class="t"><b>${esc(p.name)}</b><small>${esc(meta || p.barcode || "sem código")}</small>
      ${p.low ? `<span class="tag ${p.qty === 0 ? "zero" : ""}">${p.qty === 0 ? "Sem estoque" : "Estoque baixo"}</span>` : ""}</div>
    <div class="qty"><b>${p.qty}</b><small>mín. ${p.min_effective}</small></div></button>`;
}

function stockView() {
  const s = S.summary || { items: 0, units: 0, low: 0 };
  const groups = {};
  S.products.forEach((p) => (groups[p.category || "Sem categoria"] ||= []).push(p));
  const list = Object.keys(groups).length
    ? Object.entries(groups).map(([c, ps]) => `<div class="group"><span>${esc(c)}</span><span>${ps.length}</span></div><div class="list">${ps.map(itemRow).join("")}</div>`).join("")
    : `<div class="empty">${S.q || S.cat ? "Nenhuma peça encontrada." : "Nenhuma peça cadastrada ainda.<br>Toque em <b>+ Nova peça</b> ou use <b>Escanear</b>."}</div>`;
  const chips = [`<button class="chip" data-cat="0" aria-pressed="${!S.cat}">Todas</button>`]
    .concat(S.cats.filter((c) => c.products || c.id === S.cat).map((c) => `<button class="chip" data-cat="${c.id}" aria-pressed="${S.cat === c.id}">${esc(c.name)} (${c.products})</button>`)).join("");
  shell(`<div class="stats">
      <div class="stat"><b>${s.items}</b><span>peças cadastradas</span></div>
      <div class="stat"><b>${s.units}</b><span>unidades</span></div>
      <button class="stat ${s.low ? "warn" : ""}" data-tab="alerts"><b>${s.low}</b><span>${s.low ? "em alerta" : "sem alertas"}</span></button></div>
    <div class="search">${svg("search")}<input id="q" type="search" placeholder="Buscar por nome, código ou marca" value="${esc(S.q)}" aria-label="Buscar peça"></div>
    <div class="chips">${chips}</div>${list}
    ${S.hasMore ? '<button class="btn block ghost more" data-act="more">Mostrar mais peças</button>' : ""}
    <button class="btn fab" data-act="new">+ Nova peça</button>`);
}

function alertsView() {
  const low = S.low; // lista completa vinda do servidor, ja ordenada por quantidade
  shell(`<h2 class="page">Alertas de estoque</h2>
    <p class="muted" style="margin-top:-6px">Peças com quantidade igual ou abaixo do mínimo (padrão: <b>${S.minDefault}</b>).</p>
    ${low.length ? `<div class="list">${low.map(itemRow).join("")}</div>` : `<div class="empty">Tudo certo! Nenhuma peça com estoque baixo.</div>`}`);
}

function historyView() {
  const rows = S.moves.map((m) => {
    const lbl = m.type === "in" ? "Entrada" : m.type === "out" ? "Saída" : "Contagem";
    const cls = m.type === "adjust" ? "adj" : m.delta > 0 ? "pos" : "neg";
    const d = m.type === "adjust" ? `→ ${m.balance}` : (m.delta > 0 ? "+" : "") + m.delta;
    return `<div class="mv"><div><b>${esc(m.product)}</b><small>${lbl}${m.note ? " · " + esc(m.note) : ""} · ${esc(m.user || "")} · ${fmtDate(m.created_at)}</small></div><div class="d ${cls}">${d}</div></div>`;
  }).join("");
  shell(`<h2 class="page">Histórico</h2><div class="card">${rows || '<div class="empty">Sem movimentações ainda.</div>'}</div>`);
}

function moreView() {
  const owner = S.user.role === "dono";
  shell(`<h2 class="page">Mais</h2>
    <div class="section card"><h3>Relatórios</h3>
      <div class="setting"><div class="l">Exportar estoque<small>Planilha para Excel (CSV)</small></div><a class="btn sm ghost" href="/api/export.csv">Baixar</a></div></div>
    ${owner ? `<div class="section card"><h3>Alerta de estoque baixo</h3>
      <form id="minform" class="setting"><div class="l">Avisar quando restar até<small>Cada peça pode ter seu próprio mínimo</small></div>
      <div style="display:flex;gap:8px;width:150px"><input name="min" type="number" min="0" value="${S.minDefault}" aria-label="Mínimo padrão"><button class="btn sm">OK</button></div></form></div>
    <div class="section card"><h3>Backup</h3><div id="backupbox"><span class="muted">Carregando…</span></div>
      <button class="btn sm ghost" data-act="backup" style="margin-top:10px">Fazer backup agora</button></div>
    <div class="section card"><h3>Categorias</h3><div id="catbox"></div>
      <form id="catform" style="display:flex;gap:8px;margin-top:10px"><input name="name" placeholder="Nova categoria" required><button class="btn sm">Adicionar</button></form></div>
    <div class="section card"><h3>Usuários</h3><div id="userbox"></div>
      <button class="btn sm ghost" data-act="newuser" style="margin-top:10px">+ Novo usuário</button></div>` : `<div class="section card"><h3>Categorias</h3>
      <form id="catform" style="display:flex;gap:8px"><input name="name" placeholder="Nova categoria" required><button class="btn sm">Adicionar</button></form></div>`}
    <div class="section card"><h3>Minha conta</h3>
      <div class="setting"><div class="l">${esc(S.user.name)}<small>${S.user.role === "dono" ? "Dono" : "Atendente"} · ${esc(S.user.username)}</small></div>
      <button class="btn sm ghost" data-act="pw">Trocar senha</button></div>
      <button class="btn dark block" data-act="logout" style="margin-top:8px">Sair</button></div>`);
  if (owner) { renderCats(); renderUsers(); renderBackup(); }
  const cf = $("#catform");
  cf.onsubmit = async (e) => { e.preventDefault();
    try { await api("/categories", { method: "POST", body: { name: new FormData(cf).get("name") } }); toast("Categoria criada."); await refresh(); } catch (er) { toast(er.message, true); } };
  const mf = $("#minform");
  if (mf) mf.onsubmit = async (e) => { e.preventDefault();
    try { const r = await api("/settings", { method: "PUT", body: { min_default: new FormData(mf).get("min") } }); S.minDefault = r.min_default; toast("Mínimo atualizado."); await refresh(); } catch (er) { toast(er.message, true); } };
}
function renderCats() {
  $("#catbox").innerHTML = S.cats.map((c) => `<div class="setting"><div class="l">${esc(c.name)}<small>${c.products} peça(s)</small></div>
    <button class="btn sm ghost" data-delcat="${c.id}" aria-label="Excluir ${esc(c.name)}">Excluir</button></div>`).join("");
}
const BACKUP_LATE_MS = 48 * 3600 * 1000; // backup diario: 2 dias sem copia indica problema
function showBackup(st) {
  const late = !st.last_at || Date.now() - new Date(st.last_at.replace(" ", "T")) > BACKUP_LATE_MS;
  $("#backupbox").innerHTML = `<div class="setting"><div class="l">${st.last_at ? `Último backup: ${fmtDate(st.last_at)}` : "Nenhum backup ainda"}
    ${late ? '<span class="tag zero">Atrasado</span>' : ""}<small>${esc(st.dir)}</small></div></div>`;
}
async function renderBackup() {
  try { showBackup(await api("/backup")); } catch (e) { $("#backupbox").textContent = e.message; }
}

async function renderUsers() {
  try { const us = await api("/users");
    $("#userbox").innerHTML = us.map((u) => `<div class="setting"><div class="l">${esc(u.name)}${u.active ? "" : " (inativo)"}<small>${esc(u.username)} · ${u.role === "dono" ? "Dono" : "Atendente"}</small></div>
      <div style="display:flex;gap:6px"><button class="btn sm ghost" data-resetpw="${u.id}">Senha</button>
      ${u.id !== S.user.id ? `<button class="btn sm ghost" data-toggleuser="${u.id}" data-active="${u.active ? 0 : 1}">${u.active ? "Desativar" : "Ativar"}</button>` : ""}</div></div>`).join("");
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- scan */
let scanner = null;
async function stopCamera() { if (scanner) { try { await scanner.stop(); scanner.clear(); } catch {} scanner = null; } }
function scanView() {
  shell(`<h2 class="page">Escanear peça</h2>
    <div id="reader" hidden></div>
    <form id="scanform" class="scanbox"><input id="code" inputmode="text" autocomplete="off" placeholder="Leia o código de barras ou digite" aria-label="Código de barras"><button class="btn">Buscar</button></form>
    <button class="btn block ghost" id="cam">Usar a câmera do celular</button>
    <p class="muted" style="margin-top:14px">Com o leitor de código de barras, basta clicar no campo e ler a peça. Se ela já existir, abre para dar entrada ou saída; se não, abre o cadastro.</p>`);
  const input = $("#code");
  if (!matchMedia("(pointer: coarse)").matches) input.focus();
  $("#scanform").onsubmit = (e) => { e.preventDefault(); const v = input.value.trim(); if (v) { input.value = ""; handleCode(v); } };
  $("#cam").onclick = startCamera;
}
async function startCamera() {
  const box = $("#reader"), btn = $("#cam");
  if (scanner) { await stopCamera(); box.hidden = true; btn.textContent = "Usar a câmera do celular"; return; }
  if (!navigator.mediaDevices || !window.isSecureContext) {
    toast("A câmera só funciona em conexão segura (https). Veja o passo a passo no README.", true); return;
  }
  box.hidden = false; btn.textContent = "Fechar câmera";
  const F = Html5QrcodeSupportedFormats;
  scanner = new Html5Qrcode("reader", { formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF, F.QR_CODE], useBarCodeDetectorIfSupported: true, verbose: false });
  try {
    await scanner.start({ facingMode: "environment" }, { fps: 10, qrbox: (w) => ({ width: Math.min(300, w - 20), height: 150 }) },
      async (text) => { beep(); await stopCamera(); handleCode(text); }, () => {});
  } catch (e) {
    scanner = null; box.hidden = true; btn.textContent = "Usar a câmera do celular";
    toast("Não consegui abrir a câmera. Verifique a permissão no navegador.", true);
  }
}
async function handleCode(code) {
  try { const p = await api("/products/barcode/" + encodeURIComponent(code)); openProduct(p.id); }
  catch (e) {
    if (e.status === 404) { toast("Peça nova — preencha o cadastro."); openForm({ barcode: code }); }
    else toast(e.message, true);
  }
}

/* ---------------------------------------------------------------- sheets */
function openSheet(html) {
  sheetRoot.innerHTML = `<div class="overlay" data-close><div class="sheet" role="dialog" aria-modal="true">${html}</div></div>`;
  const first = sheetRoot.querySelector("input:not([type=hidden]), button.btn");
  if (first && !matchMedia("(pointer: coarse)").matches) first.focus();
}
function closeSheet() {
  sheetRoot.innerHTML = "";
  // Na aba Escanear, o leitor USB "digita" no campo: devolve o foco para a próxima leitura.
  const code = $("#code");
  if (code && !matchMedia("(pointer: coarse)").matches) code.focus();
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

function catOptions(sel) {
  return `<option value="">Sem categoria</option>` + S.cats.map((c) => `<option value="${c.id}" ${c.id === sel ? "selected" : ""}>${esc(c.name)}</option>`).join("");
}
function productFields(p = {}) {
  return `<label class="f"><span>Nome da peça *</span><input name="name" required value="${esc(p.name)}" placeholder="Ex.: Filtro de cabine Gol G5"></label>
    <label class="f"><span>Categoria (tipo de peça)</span><select name="category_id">${catOptions(p.category_id)}</select></label>
    <div class="row2"><label class="f"><span>Código da peça</span><input name="code" value="${esc(p.code)}"></label>
    <label class="f"><span>Marca</span><input name="brand" value="${esc(p.brand)}"></label></div>
    <div class="row2"><label class="f"><span>Código de barras</span><input name="barcode" value="${esc(p.barcode)}" inputmode="numeric"></label>
    <label class="f"><span>NCM</span><input name="ncm" value="${esc(p.ncm)}" inputmode="numeric"></label></div>
    <label class="f"><span>Mínimo para avisar (vazio = padrão ${S.minDefault})</span><input name="min_qty" type="number" min="0" value="${p.min_qty ?? ""}"></label>`;
}
const formBody = (f) => { const d = Object.fromEntries(new FormData(f)); return d; };

function openForm(prefill = {}) {
  openSheet(`<header><h3>Nova peça</h3><button class="x" data-close aria-label="Fechar">×</button></header>
    <form id="newform"><div id="ferr"></div>${productFields(prefill)}
    <label class="f"><span>Quantidade em estoque agora</span><input name="qty" type="number" min="0" value="1"></label>
    <button class="btn block">Cadastrar peça</button></form>`);
  $("#newform").onsubmit = async (e) => { e.preventDefault();
    try { const p = await api("/products", { method: "POST", body: formBody(e.target) }); closeSheet(); toast(`${p.name} cadastrada (${p.qty} un.).`); S.tab = S.tab === "scan" ? "scan" : "stock"; await refresh(); }
    catch (er) { $("#ferr").innerHTML = `<div class="err">${esc(er.message)}</div>`; } };
}

async function openProduct(id) {
  let p;
  try { p = await api("/products/" + id); } catch (e) { toast(e.message, true); return; }
  let type = "out";
  const owner = S.user.role === "dono";
  const hist = p.movements.map((m) => { const cls = m.type === "adjust" ? "adj" : m.delta > 0 ? "pos" : "neg";
    const lbl = m.type === "in" ? "Entrada" : m.type === "out" ? "Saída" : "Contagem";
    return `<div class="mv"><div>${lbl}${m.note ? " · " + esc(m.note) : ""}<small>${esc(m.user || "")} · ${fmtDate(m.created_at)}</small></div><div class="d ${cls}">${m.type === "adjust" ? "→ " + m.balance : (m.delta > 0 ? "+" : "") + m.delta}</div></div>`; }).join("");
  openSheet(`<header><div><h3>${esc(p.name)}</h3><span class="muted">${esc([p.category, p.code, p.brand].filter(Boolean).join(" · "))}</span></div><button class="x" data-close aria-label="Fechar">×</button></header>
    <div class="bigqty"><b>${p.qty}</b><span class="muted">em estoque · mínimo ${p.min_effective}</span> ${p.low ? `<span class="tag ${p.qty === 0 ? "zero" : ""}">${p.qty === 0 ? "Sem estoque" : "Estoque baixo"}</span>` : ""}</div>
    <div id="merr"></div>
    <div class="seg" role="group" aria-label="Tipo de movimentação">
      <button class="out" data-type="out" aria-pressed="true">Saída</button><button class="in" data-type="in" aria-pressed="false">Entrada</button><button data-type="adjust" aria-pressed="false">Contagem</button></div>
    <div class="stepper"><button data-step="-1" aria-label="Menos">−</button><input id="mqty" type="number" inputmode="numeric" min="1" value="1" aria-label="Quantidade"><button data-step="1" aria-label="Mais">+</button></div>
    <label class="f"><span id="nlabel">Observação (opcional)</span><input id="mnote" placeholder="Ex.: venda sem nota, OS 123"></label>
    <button class="btn block" id="mgo">Registrar saída</button>
    <div class="hist"><h4>Últimas movimentações</h4>${hist || '<span class="muted">Nenhuma ainda.</span>'}</div>
    <details class="edit"><summary>Editar dados da peça</summary><form id="editform">${productFields(p)}
      <button class="btn block">Salvar alterações</button>${owner ? `<button type="button" class="btn danger block" id="del" style="margin-top:8px">Excluir peça</button>` : ""}</form></details>`);
  const qty = $("#mqty"), go = $("#mgo");
  const setType = (t) => { type = t;
    sheetRoot.querySelectorAll("[data-type]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.type === t));
    go.textContent = t === "in" ? "Registrar entrada" : t === "out" ? "Registrar saída" : "Salvar contagem";
    qty.min = t === "adjust" ? 0 : 1; qty.value = t === "adjust" ? p.qty : 1;
    $("#nlabel").textContent = t === "adjust" ? "Quantidade real contada" : "Observação (opcional)"; };
  sheetRoot.querySelectorAll("[data-type]").forEach((b) => (b.onclick = () => setType(b.dataset.type)));
  sheetRoot.querySelectorAll("[data-step]").forEach((b) => (b.onclick = () => { qty.value = Math.max(Number(qty.min), (Number(qty.value) || 0) + Number(b.dataset.step)); }));
  go.onclick = async () => { go.disabled = true;
    try { const r = await api(`/products/${id}/move`, { method: "POST", body: { type, qty: qty.value, note: $("#mnote").value } });
      closeSheet(); toast(`${r.name}: agora ${r.qty} em estoque.`); await refresh(); }
    catch (e) { $("#merr").innerHTML = `<div class="err">${esc(e.message)}</div>`; go.disabled = false; } };
  $("#editform").onsubmit = async (e) => { e.preventDefault();
    try { await api("/products/" + id, { method: "PUT", body: formBody(e.target) }); closeSheet(); toast("Dados salvos."); await refresh(); }
    catch (er) { $("#merr").innerHTML = `<div class="err">${esc(er.message)}</div>`; } };
  const del = $("#del");
  if (del) del.onclick = async () => { if (!confirm(`Excluir "${p.name}"? O histórico será mantido.`)) return;
    try { await api("/products/" + id, { method: "DELETE" }); closeSheet(); toast("Peça excluída."); await refresh(); } catch (e) { toast(e.message, true); } };
}

function openPw() {
  openSheet(`<header><h3>Trocar senha</h3><button class="x" data-close aria-label="Fechar">×</button></header>
    <form id="pwform"><div id="perr"></div>
    <label class="f"><span>Senha atual</span><input name="current" type="password" required autocomplete="current-password"></label>
    <label class="f"><span>Nova senha</span><input name="new" type="password" required minlength="8" autocomplete="new-password"></label>
    <button class="btn block">Salvar</button></form>`);
  $("#pwform").onsubmit = async (e) => { e.preventDefault();
    try { await api("/password", { method: "POST", body: formBody(e.target) }); closeSheet(); toast("Senha alterada."); } catch (er) { $("#perr").innerHTML = `<div class="err">${esc(er.message)}</div>`; } };
}
function openUserForm(reset) {
  openSheet(`<header><h3>${reset ? "Nova senha" : "Novo usuário"}</h3><button class="x" data-close aria-label="Fechar">×</button></header>
    <form id="uform"><div id="uerr"></div>
    ${reset ? "" : `<label class="f"><span>Nome</span><input name="name" required></label>
    <label class="f"><span>Usuário (para entrar)</span><input name="username" required autocapitalize="none"></label>`}
    <label class="f"><span>Senha</span><input name="password" type="password" required minlength="8" autocomplete="new-password"></label>
    ${reset ? "" : `<label class="f"><span>Perfil</span><select name="role"><option value="atendente">Atendente</option><option value="dono">Dono (acesso total)</option></select></label>`}
    <button class="btn block">Salvar</button></form>`);
  $("#uform").onsubmit = async (e) => { e.preventDefault();
    try { if (reset) await api("/users/" + reset, { method: "PUT", body: formBody(e.target) }); else await api("/users", { method: "POST", body: formBody(e.target) });
      closeSheet(); toast("Salvo."); renderUsers(); } catch (er) { $("#uerr").innerHTML = `<div class="err">${esc(er.message)}</div>`; } };
}

/* ---------------------------------------------------------------- events */
let searchTimer;
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-tab],[data-open],[data-cat],[data-act],[data-close],[data-delcat],[data-resetpw],[data-toggleuser]");
  if (!t) return;
  if (t.hasAttribute("data-close")) { if (t.classList.contains("overlay") && e.target !== t) return; closeSheet(); return; }
  if (t.dataset.tab) { await stopCamera(); S.tab = t.dataset.tab; await loadTabData().catch((er) => toast(er.message, true)); render(); window.scrollTo(0, 0); return; }
  if (t.dataset.open) return openProduct(t.dataset.open);
  if (t.dataset.cat !== undefined) { S.cat = Number(t.dataset.cat); await reloadProducts(); return; }
  if (t.dataset.delcat) { if (!confirm("Excluir esta categoria?")) return; try { await api("/categories/" + t.dataset.delcat, { method: "DELETE" }); await refresh(); } catch (er) { toast(er.message, true); } return; }
  if (t.dataset.resetpw) return openUserForm(t.dataset.resetpw);
  if (t.dataset.toggleuser) { try { await api("/users/" + t.dataset.toggleuser, { method: "PUT", body: { active: t.dataset.active === "1" } }); renderUsers(); } catch (er) { toast(er.message, true); } return; }
  switch (t.dataset.act) {
    case "new": return openForm();
    case "more": t.disabled = true;
      try { if (await loadProducts(true)) render(); } catch (er) { toast(er.message, true); t.disabled = false; }
      return;
    case "pw": return openPw();
    case "newuser": return openUserForm();
    case "backup": t.disabled = true;
      try { showBackup(await api("/backup", { method: "POST" })); toast("Backup salvo."); } catch (er) { toast(er.message, true); }
      t.disabled = false; return;
    case "logout": await api("/logout", { method: "POST" }); S.user = null; await boot(); return;
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id !== "q") return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    S.q = e.target.value.trim(); const pos = e.target.selectionStart;
    if (!(await reloadProducts())) return;
    const q = $("#q"); if (q) { q.focus(); q.setSelectionRange(pos, pos); }
  }, 250);
});

/* ---------------------------------------------------------------- boot */
function render() {
  if (!S.user) return authView();
  ({ stock: stockView, alerts: alertsView, scan: scanView, history: historyView, more: moreView }[S.tab] || stockView)();
}
async function boot() {
  try {
    const st = await api("/state");
    S.user = st.user; S.setupNeeded = st.setup_needed; S.setupHere = st.setup_here; S.minDefault = st.min_default;
    if (S.user) { S.tab = "stock"; S.q = ""; S.cat = 0; await loadAll(); }
  } catch (e) { app.innerHTML = `<div class="login"><div class="err">${esc(e.message)}</div></div>`; return; }
  render();
}
boot();
