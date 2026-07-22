/**
 * Metadados NÃO-secretos do agente (agent_id, nome, URL do backend pareado).
 * O token vive só no cofre do SO (token-vault.js) — isto aqui é o resto, que
 * não tem problema em ficar num JSON comum.
 *
 * `backendUrl` é fixado (pin) no momento do pareamento e nunca trocado por um
 * comando remoto — Seção 5: "o agente ... não aceita redirecionamento pra
 * outro host". Trocar de backend exige reparear (apagar o arquivo e rodar
 * `npm run pair` de novo), uma ação local, nunca uma mensagem da rede.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DIR = path.join(os.homedir(), ".jarvis-agente");
const FILE = path.join(DIR, "config.json");

export function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(FILE, "utf8"));
  } catch {
    return null;
  }
}

export function saveConfig(cfg) {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

export function clearConfig() {
  fs.rmSync(FILE, { force: true });
}

export function auditLogPath() {
  return path.join(DIR, "audit.local.jsonl");
}

export function dataDir() {
  return DIR;
}
