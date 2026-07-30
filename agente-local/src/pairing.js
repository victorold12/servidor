/**
 * Cliente do fluxo de pareamento (RFC 8628 — Seção 3 do esquema). Fala HTTP
 * com /api/pair/start e /api/pair/poll, que já existem no backend
 * (app/routers/pairing.py). Puro I/O de rede, sem decisão de segurança aqui —
 * essa já foi tomada no servidor (trava de tentativas, TTL, hash do device_code).
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * @param {object} opts
 * @param {string} opts.backendUrl   ex. "https://meuservidor.onrender.com" (sem barra final)
 * @param {string} opts.name         nome do dispositivo, ex. "PC-VICTOR"
 * @param {string} opts.platform     "win32" | "darwin" | "linux"
 * @param {(evt:{type:string, [k:string]:any})=>void} [opts.onEvent]  progresso (pra UI/CLI)
 * @param {AbortSignal} [opts.signal]
 * @param {typeof fetch} [opts.fetchFn]
 * @returns {Promise<{agentId:string, agentToken:string, allowedRoots:string[]}>}
 */
export async function pairWithBackend({ backendUrl, name, platform, onEvent, signal, fetchFn = fetch }) {
  const base = backendUrl.replace(/\/+$/, "");
  const emit = (evt) => onEvent?.(evt);

  const startRes = await fetchFn(`${base}/api/pair/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, platform }),
  });
  if (!startRes.ok) {
    throw new Error(`Não consegui iniciar o pareamento (HTTP ${startRes.status}). O backend está no ar em ${base}?`);
  }
  const { device_code, user_code, interval, expires_in } = await startRes.json();
  emit({ type: "code", userCode: user_code, expiresIn: expires_in });

  const deadline = Date.now() + expires_in * 1000;
  let waitMs = Math.max(1, interval) * 1000;
  let consecutiveNetworkFailures = 0;

  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error("Pareamento cancelado.");
    await sleep(waitMs);

    let res;
    try {
      res = await fetchFn(`${base}/api/pair/poll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_code }),
      });
    } catch (err) {
      consecutiveNetworkFailures += 1;
      if (consecutiveNetworkFailures >= 5) throw new Error(`Sem conexão com o backend: ${err.message}`);
      emit({ type: "network-retry", error: err.message });
      continue;
    }
    consecutiveNetworkFailures = 0;

    if (res.status === 429) {
      // Rate limit dedicado do backend (Seção 14) — não é erro, é "diminui o ritmo".
      waitMs = Math.min(waitMs + 2000, 15_000);
      emit({ type: "slow_down", waitMs });
      continue;
    }
    if (!res.ok) throw new Error(`Erro inesperado no poll (HTTP ${res.status}).`);

    const data = await res.json();
    if (data.status === "pending") {
      emit({ type: "pending" });
      continue;
    }
    if (data.status === "approved") {
      emit({ type: "approved" });
      return { agentId: data.agent_id, agentToken: data.agent_token, allowedRoots: data.allowed_roots || [] };
    }
    if (data.status === "denied") {
      throw new Error("Pareamento negado (ou travado por 5 tentativas de código erradas). Gere um novo código.");
    }
    if (data.status === "expired") {
      throw new Error("O código expirou antes de ser confirmado. Gere um novo.");
    }
    throw new Error(`Status inesperado do backend: ${data.status}`);
  }
  throw new Error("Tempo esgotado (10 min) esperando você confirmar o código.");
}
