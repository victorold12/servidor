/* Roda em toda página (Seção 6 do esquema). Só executa quando o popup pede via
 * mensagem — não manda nada pra fora sozinho, não observa a página em segundo
 * plano. O popup é quem decide se/quando usar o resultado.
 */
function extractPage() {
  const title = document.title || "";
  const url = location.href;
  // Corpo de texto legível: remove script/style/nav/footer pra não poluir com
  // ruído de layout — o que sobra é o que um leitor humano realmente veria.
  const clone = document.body ? document.body.cloneNode(true) : null;
  if (clone) {
    clone.querySelectorAll("script, style, nav, footer, noscript, svg").forEach((el) => el.remove());
  }
  const text = (clone?.innerText || document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
  return { title, url, text: text.slice(0, 20000) };
}

function getSelectionText() {
  return String(window.getSelection?.() || "").trim();
}

/* Preenche campos de formulário visíveis cujo name/id/autocomplete/label bata
 * com um perfil simples {name, email, phone}. Heurística por palavra-chave —
 * não é IA, é reconhecimento de padrão comum de formulário (Seção 6). */
const FIELD_PATTERNS = {
  name: /\b(name|nome|full-?name|fullname)\b/i,
  email: /\b(email|e-mail)\b/i,
  phone: /\b(phone|tel|telefone|celular|whatsapp)\b/i,
};

function fieldSignature(el) {
  return [el.name, el.id, el.getAttribute("autocomplete"), el.placeholder, el.getAttribute("aria-label")]
    .filter(Boolean)
    .join(" ");
}

function fillForm(profile) {
  const inputs = Array.from(document.querySelectorAll("input, textarea")).filter((el) => {
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && !el.disabled && !el.readOnly;
  });
  let filled = 0;
  for (const el of inputs) {
    const sig = fieldSignature(el);
    for (const [key, re] of Object.entries(FIELD_PATTERNS)) {
      if (profile[key] && re.test(sig)) {
        el.focus();
        // Setter nativo, não el.value= direto: frameworks (React etc.) que
        // escutam via property descriptor customizado não percebem atribuição
        // direta — sem isso o campo "parece" preenchido mas o form não valida.
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, profile[key]);
        else el.value = profile[key];
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        filled++;
        break;
      }
    }
  }
  return { filled };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.action === "extract") {
    sendResponse(extractPage());
  } else if (msg?.action === "getSelection") {
    sendResponse({ text: getSelectionText() });
  } else if (msg?.action === "fillForm") {
    sendResponse(fillForm(msg.profile || {}));
  }
  return false; // resposta síncrona — sem canal assíncrono aberto
});
