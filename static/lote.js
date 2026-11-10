"use strict";
/* Leitura em sequência (aba Escanear): várias peças lidas seguidas e gravadas de uma vez pela rota de lote.
   Entrada (chegada de mercadoria) ou Contagem (só o dono). Usa as funções gerais do app.js (api, esc, $, toast,
   onSubmit, showError, newRequestId, openForm, refresh), que é carregado depois deste arquivo. */

/* Estado da sequência, guardado no navegador por usuário: a lista sobrevive a um recarregamento da página. */
const SEQ = { on: false, type: "in", items: [], unknown: [], note: "", rid: null };
let seqUser = null, seqQueue = Promise.resolve(), lastCameraRead = { code: "", at: 0 };
const seqKey = () => `maxx-sequencia-${S.user.id}`;
const isOwner = () => S.user.role === "dono";

function seqLoad() {
  if (seqUser === S.user.id) return;
  seqUser = S.user.id;
  Object.assign(SEQ, { on: false, type: "in", items: [], unknown: [], note: "", rid: null });
  try { Object.assign(SEQ, JSON.parse(localStorage.getItem(seqKey())) || {}); } catch { /* sem armazenamento: começa vazia */ }
  if (SEQ.type === "adjust" && !isOwner()) SEQ.type = "in";
}
function seqSave() {
  try { localStorage.setItem(seqKey(), JSON.stringify(SEQ)); } catch { /* sem armazenamento: só não sobrevive ao recarregar */ }
}
/* A lista mudou: é outro pedido (novo id para o reenvio seguro). */
function seqChanged(rerender = true) {
  SEQ.rid = null; seqSave();
  if (rerender) renderSeq(); else updateSeqButton();
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
function seqButtonText() {
  const n = SEQ.items.length, units = SEQ.items.reduce((s, i) => s + i.qty, 0);
  return SEQ.type === "adjust" ? `Salvar contagem de ${plural(n, "peça", "peças")}`
    : `Registrar entrada de ${plural(n, "peça", "peças")} (${plural(units, "unidade", "unidades")})`;
}
function updateSeqButton() {
  const go = $("#batchgo");
  if (go) { go.textContent = seqButtonText(); go.disabled = !SEQ.items.length; }
}

/* Seletor de modo da aba Escanear e o painel da sequência (ou a ajuda do modo de uma peça). */
function scanModeHtml() {
  seqLoad();
  return `<div class="seg mode" role="group" aria-label="Modo de leitura">
    <button type="button" data-seq="0" aria-pressed="${!SEQ.on}">Uma peça por vez</button>
    <button type="button" data-seq="1" aria-pressed="${SEQ.on}">Leitura em sequência</button></div>`;
}
function renderSeq() {
  const box = $("#batch");
  if (!box) return;
  if (!SEQ.on) {
    box.innerHTML = `<p class="muted">Com o leitor de código de barras, basta clicar no campo e ler a peça. Se ela já existir,
      abre para dar entrada ou saída; se não, abre o cadastro.</p>`;
    return;
  }
  const adjust = SEQ.type === "adjust";
  const rows = SEQ.items.map((i) => `<div class="item bitem" data-batch-id="${i.id}">
      <div class="t"><b>${esc(i.name)}</b><small>${adjust ? "no sistema" : "em estoque"}: ${i.seen}</small></div>
      <input type="number" inputmode="numeric" min="${adjust ? 0 : 1}" value="${i.qty}" aria-label="Quantidade de ${esc(i.name)}">
      <button type="button" class="x" data-seq-del="${i.id}" aria-label="Remover ${esc(i.name)}">×</button></div>`).join("");
  const unknown = SEQ.unknown.map((c) => `<div class="unknown"><span>Código <b>${esc(c)}</b>: peça não cadastrada</span>
      <button type="button" class="btn sm ghost" data-seq-new="${esc(c)}">Cadastrar</button>
      <button type="button" class="x" data-seq-forget="${esc(c)}" aria-label="Descartar o código ${esc(c)}">×</button></div>`).join("");
  box.innerHTML = `<div class="seg" role="group" aria-label="O que a sequência registra">
      <button type="button" class="in" data-batch-type="in" aria-pressed="${!adjust}">Entrada</button>
      ${isOwner() ? `<button type="button" data-batch-type="adjust" aria-pressed="${adjust}">Contagem</button>` : ""}</div>
    <p class="muted">${adjust ? "Leia cada unidade de cada peça: o total lido vira o saldo da peça."
      : "Cada leitura soma 1 na peça. Corrija a quantidade na lista se precisar."}</p>
    <div id="batcherr"></div>
    <div class="list">${rows || '<div class="empty">Nenhuma peça lida ainda.</div>'}</div>${unknown}
    <form id="batchform" class="batchform">
      <label class="f"><span>Observação (opcional)</span><input id="batchnote" value="${esc(SEQ.note)}" placeholder="Ex.: NF 4471, fornecedor"></label>
      <button class="btn block ${adjust ? "adjust" : "in"}" id="batchgo"></button>
      <button type="button" class="btn block ghost" data-seq-clear>Limpar lista</button></form>`;
  updateSeqButton();
  box.querySelectorAll(".bitem input").forEach((inp) => (inp.oninput = () => {
    const it = SEQ.items.find((i) => i.id === Number(inp.closest(".bitem").dataset.batchId));
    const n = Number(inp.value);
    if (it && Number.isInteger(n) && n >= Number(inp.min)) { it.qty = n; seqChanged(false); }
  }));
  $("#batchnote").oninput = (e) => { SEQ.note = e.target.value; seqChanged(false); };
  onSubmit($("#batchform"), seqSubmit);
}

/* Uma leitura na sequência: soma 1 na peça ou guarda o código desconhecido. Em fila, para leituras rápidas do
   leitor USB não criarem a mesma peça duas vezes. */
function seqAdd(code) {
  seqQueue = seqQueue.then(async () => {
    try {
      const p = await api("/products/barcode/" + encodeURIComponent(code));
      const it = SEQ.items.find((i) => i.id === p.id);
      if (it) it.qty += 1; else SEQ.items.push({ id: p.id, name: p.name, qty: 1, seen: p.qty });
      seqChanged();
    } catch (e) {
      if (e.status !== 404) { toast(e.message, true); return; }
      if (!SEQ.unknown.includes(code)) SEQ.unknown.push(code);
      toast("Código não cadastrado: ficou na lista para cadastrar depois.");
      seqChanged();
    }
  });
  return seqQueue;
}
/* Câmera na sequência: continua aberta; a mesma etiqueta parada na frente dela conta uma vez só. */
function seqCameraRead(text) {
  if (!SEQ.on) return false;
  const now = Date.now();
  if (text === lastCameraRead.code && now - lastCameraRead.at < 2000) return true;
  lastCameraRead = { code: text, at: now };
  beep(); seqAdd(text);
  return true;
}

async function seqSubmit() {
  const adjust = SEQ.type === "adjust";
  const body = { type: SEQ.type, note: SEQ.note, request_id: (SEQ.rid ||= newRequestId()),
    items: SEQ.items.map((i) => ({ product_id: i.id, qty: i.qty, ...(adjust ? { expected: i.seen } : {}) })) };
  seqSave();
  try {
    await api("/products/moves", { method: "POST", body });
    const n = plural(SEQ.items.length, "peça", "peças");
    Object.assign(SEQ, { items: [], note: "", rid: null }); seqSave();
    toast(adjust ? `Contagem salva: ${n}.` : `Entrada registrada: ${n}.`);
    await refresh();
  } catch (e) {
    if (e.status === 409 && Array.isArray(e.data.changed)) { // alguém mexeu no estoque: confere e salva de novo
      e.data.changed.forEach((c) => { const it = SEQ.items.find((i) => i.id === c.product_id); if (it) it.seen = c.qty; });
      seqChanged();
    }
    showError("#batcherr", e);
  }
}

/* Cliques do painel (ligados uma vez; o painel é redesenhado a cada leitura). */
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-seq],[data-batch-type],[data-seq-del],[data-seq-new],[data-seq-forget],[data-seq-clear]");
  if (!t) return;
  if (t.dataset.seq !== undefined) { SEQ.on = t.dataset.seq === "1"; seqSave(); render(); return; }
  if (t.dataset.batchType) { SEQ.type = t.dataset.batchType; seqChanged(); }
  else if (t.dataset.seqDel) { SEQ.items = SEQ.items.filter((i) => i.id !== Number(t.dataset.seqDel)); seqChanged(); }
  else if (t.dataset.seqForget) { SEQ.unknown = SEQ.unknown.filter((c) => c !== t.dataset.seqForget); seqChanged(); }
  else if (t.dataset.seqNew) {
    const code = t.dataset.seqNew;
    openForm({ barcode: code }, () => { SEQ.unknown = SEQ.unknown.filter((c) => c !== code); seqSave(); });
    return;
  } else if (t.hasAttribute("data-seq-clear")) {
    if (!confirm("Limpar a lista da sequência? Nada foi gravado ainda.")) return;
    Object.assign(SEQ, { items: [], unknown: [], note: "" }); seqChanged();
  }
  const code = $("#code");
  if (code && hasMouse()) code.focus(); // o leitor USB continua lendo sem clicar no campo
});
