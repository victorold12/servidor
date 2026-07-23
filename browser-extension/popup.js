/* Lógica do popup. Fala DIRETO com o backend do JARVIS (Seção 6 — não com o
 * Electron/app), usando a mesma URL + token de acesso configurados no site.
 * Content script só é acionado por mensagem explícita, nunca sozinho.
 */
const STORAGE_KEYS = ["backendUrl", "backendToken", "profileName", "profileEmail", "profilePhone"];

function $(id) { return document.getElementById(id); }

function setStatus(el, text, kind) {
  el.textContent = text || "";
  el.className = "status" + (kind ? " " + kind : "");
}

async function getConfig() {
  return new Promise((resolve) => chrome.storage.local.get(STORAGE_KEYS, resolve));
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function sendToTab(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(response);
    });
  });
}

async function backendFetch(cfg, path, body) {
  if (!cfg.backendUrl) throw new Error("Configure a URL do backend primeiro.");
  const headers = { "Content-Type": "application/json" };
  if (cfg.backendToken) headers["X-Backend-Token"] = cfg.backendToken;
  const r = await fetch(cfg.backendUrl.replace(/\/$/, "") + path, {
    method: "POST",
    headers,
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

document.addEventListener("DOMContentLoaded", async () => {
  const cfg = await getConfig();
  if (cfg.backendUrl) $("backend-url").value = cfg.backendUrl;
  if (cfg.backendToken) $("backend-token").value = cfg.backendToken;
  if (cfg.profileName) $("profile-name").value = cfg.profileName;
  if (cfg.profileEmail) $("profile-email").value = cfg.profileEmail;
  if (cfg.profilePhone) $("profile-phone").value = cfg.profilePhone;

  $("save-backend").onclick = async () => {
    await chrome.storage.local.set({
      backendUrl: $("backend-url").value.trim(),
      backendToken: $("backend-token").value.trim(),
    });
    setStatus($("backend-status"), "Salvo.", "ok");
  };

  $("btn-extract").onclick = async () => {
    const box = $("page-result");
    box.style.display = "block";
    box.textContent = "Extraindo…";
    try {
      const tab = await activeTab();
      const data = await sendToTab(tab.id, { action: "extract" });
      box.textContent = `${data.title}\n${data.url}\n\n${data.text.slice(0, 3000)}`;
    } catch (e) {
      box.textContent = "Erro: " + e.message + " (a página precisa estar carregada e não ser uma aba interna do navegador)";
    }
  };

  $("btn-selection").onclick = async () => {
    const box = $("page-result");
    box.style.display = "block";
    try {
      const tab = await activeTab();
      const data = await sendToTab(tab.id, { action: "getSelection" });
      box.textContent = data.text || "(nada selecionado na página)";
    } catch (e) {
      box.textContent = "Erro: " + e.message;
    }
  };

  $("btn-search").onclick = async () => {
    const q = $("search-q").value.trim();
    const statusEl = $("search-status");
    const resultsEl = $("search-results");
    resultsEl.innerHTML = "";
    if (!q) { setStatus(statusEl, "Digite algo pra pesquisar.", "err"); return; }
    setStatus(statusEl, "Pesquisando…");
    try {
      const cfg = await getConfig();
      const data = await backendFetch(cfg, "/api/search", { q, max: 5 });
      const results = data.results || [];
      setStatus(statusEl, results.length ? "" : "Nenhum resultado.", results.length ? "" : "err");
      resultsEl.innerHTML = results.map((r) => `
        <div class="search-item">
          <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.url)}</a>
          <div class="snippet">${esc((r.snippet || "").slice(0, 140))}</div>
        </div>
      `).join("");
    } catch (e) {
      setStatus(statusEl, "Erro: " + e.message, "err");
    }
  };

  $("btn-fill").onclick = async () => {
    const statusEl = $("fill-status");
    const profile = {
      name: $("profile-name").value.trim(),
      email: $("profile-email").value.trim(),
      phone: $("profile-phone").value.trim(),
    };
    await chrome.storage.local.set({ profileName: profile.name, profileEmail: profile.email, profilePhone: profile.phone });
    if (!profile.name && !profile.email && !profile.phone) {
      setStatus(statusEl, "Preencha ao menos um campo do perfil.", "err");
      return;
    }
    setStatus(statusEl, "Preenchendo…");
    try {
      const tab = await activeTab();
      const data = await sendToTab(tab.id, { action: "fillForm", profile });
      setStatus(statusEl, `${data.filled} campo(s) preenchido(s).`, data.filled ? "ok" : "err");
    } catch (e) {
      setStatus(statusEl, "Erro: " + e.message, "err");
    }
  };
});
