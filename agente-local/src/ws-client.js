/**
 * Cliente do hub WebSocket (/ws/agent — Seções 5 e 12). O agente é sempre
 * CLIENTE: abre a conexão de SAÍDA e mantém, nunca escuta porta nenhuma.
 *
 * Auth vai por query param (`?token=`), não header: o WebSocket padrão (e o
 * global nativo do Node) não permite setar headers arbitrários no handshake —
 * é limitação do próprio construtor, não bug. O backend já suporta os dois
 * (ver agents_hub.py), então usamos o que o cliente real consegue fazer.
 *
 * code=4401 no close = token inválido/revogado — backend confirmado a ACEITAR
 * antes de fechar, exatamente pra esse code chegar aqui (ver histórico do
 * fix em agents_hub.py). Só nesse caso paramos de reconectar; qualquer outro
 * close (rede, restart do backend) tenta de novo com backoff.
 */
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const UNAUTHORIZED_CODE = 4401;

function toWsUrl(httpUrl) {
  return httpUrl.replace(/\/+$/, "").replace(/^http/, "ws");
}

/**
 * @param {object} opts
 * @param {string} opts.backendUrl  URL pinada no pareamento (http/https — convertida pra ws/wss)
 * @param {string} opts.token       agent_token (do token-vault)
 * @param {(msg:object)=>Promise<{ok:boolean, data?:any}>} opts.onCommand
 *        chamado pra cada {type:"command"} recebido; o retorno vira o {type:"result"}.
 * @param {(evt:object)=>void} [opts.onEvent]  ciclo de vida da conexão (log/UI)
 * @param {number} [opts.heartbeatMs]
 * @param {typeof WebSocket} [opts.WebSocketImpl]  injetável pra teste
 * @returns {{close():void, sendAudit(entry:object):void}}
 */
export function createAgentConnection({
  backendUrl,
  token,
  onCommand,
  onEvent = () => {},
  heartbeatMs = 25_000,
  WebSocketImpl,
}) {
  // Não usa `WebSocketImpl = WebSocket` no default do parâmetro: se o global
  // não existir, isso levantaria um ReferenceError críptico na hora de montar
  // os argumentos, antes até de entrar na função. Resolve aqui pra poder dar
  // um erro que diz o que fazer (Node 22+ tem WebSocket nativo; versões
  // anteriores não garantem isso).
  WebSocketImpl = WebSocketImpl || (typeof WebSocket !== "undefined" ? WebSocket : null);
  if (!WebSocketImpl) {
    throw new Error(
      `WebSocket global indisponível (Node ${process.version}). O Agente Local precisa do Node 22 ou mais novo — é de onde vem o cliente WebSocket nativo que ele usa.`
    );
  }
  const wsUrl = `${toWsUrl(backendUrl)}/ws/agent?token=${encodeURIComponent(token)}`;
  let ws = null;
  let stopped = false;
  let reconnectAttempt = 0;
  let heartbeatTimer = null;
  let reconnectTimer = null;

  function safeSend(obj) {
    if (ws && ws.readyState === WebSocketImpl.OPEN) ws.send(JSON.stringify(obj));
  }

  function scheduleReconnect() {
    if (stopped) return;
    const backoff = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempt);
    const delay = Math.round(backoff * (0.75 + Math.random() * 0.5)); // jitter ±25%
    reconnectAttempt += 1;
    onEvent({ type: "reconnecting", inMs: delay, attempt: reconnectAttempt });
    reconnectTimer = setTimeout(connect, delay);
  }

  function connect() {
    if (stopped) return;
    onEvent({ type: "connecting" });
    ws = new WebSocketImpl(wsUrl);

    ws.addEventListener("open", () => {
      reconnectAttempt = 0;
      onEvent({ type: "open" });
      heartbeatTimer = setInterval(() => safeSend({ type: "heartbeat" }), heartbeatMs);
    });

    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "command") {
        handleCommand(msg);
      } else if (msg.type === "revoked") {
        onEvent({ type: "revoked" });
        close(); // servidor revogou — não adianta reconectar com o mesmo token
      } else if (msg.type === "policy_update") {
        onEvent({ type: "policy_update", allowedRoots: msg.allowed_roots || [] });
      }
    });

    ws.addEventListener("close", (ev) => {
      clearInterval(heartbeatTimer);
      onEvent({ type: "close", code: ev.code });
      if (ev.code === UNAUTHORIZED_CODE) {
        onEvent({ type: "unauthorized" });
        stopped = true; // token morto: reconectar só bateria na mesma parede
        return;
      }
      scheduleReconnect();
    });

    ws.addEventListener("error", () => onEvent({ type: "error" }));
  }

  async function handleCommand(msg) {
    let result;
    try {
      result = await onCommand(msg);
    } catch (err) {
      result = { ok: false, data: { error: String(err?.message || err) } };
    }
    safeSend({ type: "result", id: msg.id, ok: !!result?.ok, data: result?.data ?? null });
  }

  function sendAudit(entry) {
    safeSend({ type: "audit", ...entry });
  }

  function close() {
    stopped = true;
    clearTimeout(reconnectTimer);
    clearInterval(heartbeatTimer);
    ws?.close();
  }

  connect();
  return { close, sendAudit };
}
