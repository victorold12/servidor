#!/usr/bin/env node
/**
 * Ponto de entrada do Agente Local (`npm start`). Assume que já foi pareado
 * (`npm run pair`). Conecta no hub, mantém, e despacha comandos recebidos.
 *
 * Fino de propósito: cada peça (vault, ws-client, confirm, dispatcher) já é
 * testada isoladamente. Aqui só amarra — nada de lógica nova.
 */
import { loadConfig, saveConfig } from "./config.js";
import { getToken } from "./token-vault.js";
import { createAgentConnection } from "./ws-client.js";
import { createNativeConfirm } from "./confirm.js";
import { createCommandHandler } from "./command-dispatcher.js";

async function main() {
  const cfg = loadConfig();
  if (!cfg) {
    console.error('Nenhum pareamento encontrado. Rode primeiro:  npm run pair');
    process.exitCode = 1;
    return;
  }

  const token = await getToken(); // lança se o cofre do SO não estiver disponível — de propósito (token-vault.js)
  if (!token) {
    console.error('Token não encontrado no cofre do SO. Rode "npm run pair" de novo.');
    process.exitCode = 1;
    return;
  }

  let allowedRoots = cfg.allowedRoots || [];
  // Rodando como serviço do Windows (Session 0), não existe desktop pra mostrar
  // o diálogo nativo de confirmação — ele nunca chegaria no usuário, só
  // travaria ou falharia de um jeito imprevisível. Em vez disso, nega Tier 2
  // direto (o mesmo fail-safe que já existe pra "sem confirmFn" em
  // safe-exec.js): só Tier 0/1 rodam sozinhos como serviço; Tier 2 fica pra
  // quando o Agente Local roda com o usuário logado (npm start / Electron
  // tray). Ver scripts/install-windows-service.js.
  const confirmFn = process.env.JARVIS_SERVICE_MODE === "1" ? async () => "deny" : createNativeConfirm();

  const conn = createAgentConnection({
    backendUrl: cfg.backendUrl,
    token,
    onEvent: (evt) => {
      if (evt.type === "policy_update") {
        allowedRoots = evt.allowedRoots || [];
        saveConfig({ ...cfg, allowedRoots });
      }
      logEvent(evt);
    },
    onCommand: createCommandHandler({
      getAllowedRoots: () => allowedRoots,
      confirmFn,
      sendAudit: (entry) => conn.sendAudit(entry),
      // Tier 3 é bloqueio duro por padrão — nenhum item liberado sem uma UI de
      // configuração explícita, que ainda não existe. Ver Seção 6 do esquema.
      isUnlocked: () => false,
    }),
  });

  const shutdown = () => {
    conn.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  console.log(`[jarvis-agente] "${cfg.name}" conectando em ${cfg.backendUrl}...`);
}

function logEvent(evt) {
  const { type, ...rest } = evt;
  const extra = Object.keys(rest).length ? JSON.stringify(rest) : "";
  console.log(`[jarvis-agente] ${type} ${extra}`);
}

main().catch((err) => {
  console.error("Falha ao iniciar o Agente Local:", err.message);
  process.exitCode = 1;
});
