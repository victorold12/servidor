#!/usr/bin/env node
/**
 * Registra o Agente Local como serviço do Windows (Seção 10 do prompt mestre:
 * "roda como serviço do Windows" — start automático no boot, sem precisar de
 * login manual). Usa node-windows, que por baixo gera um wrapper WinSW e chama
 * `sc.exe create`.
 *
 * LIMITAÇÃO HONESTA: um serviço roda em Session 0, sem desktop interativo —
 * o diálogo nativo de confirmação (Tier 2, Seção 7) não tem como aparecer pro
 * usuário. src/index.js detecta JARVIS_SERVICE_MODE=1 (setado aqui embaixo) e
 * nega Tier 2 automaticamente em vez de tentar mostrar um diálogo que nunca
 * chegaria em lugar nenhum. Rodando como serviço, só Tier 0/1 (leitura e
 * escrita na allowlist) funcionam sozinhos; ações Tier 2 continuam precisando
 * do Agente Local rodando com um usuário logado (`npm start` ou o Electron
 * tray) pra poder perguntar.
 *
 * Exige: rodar num terminal com privilégio de Administrador no Windows
 * (`sc.exe create` exige isso). Já deve ter pareado antes (`npm run pair`).
 */
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import pkg from "node-windows";

const { Service } = pkg;

if (os.platform() !== "win32") {
  console.error("Serviço do Windows só existe no Windows. Neste SO, use `npm start` normal.");
  process.exit(1);
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(HERE, "..", "src", "index.js");

const svc = new Service({
  name: "JARVIS Agente Local",
  description: "Cliente do JARVIS que executa ações no PC sob as 4 camadas de risco (Tier 0/1 automáticos; Tier 2 fica indisponível rodando como serviço — precisa de sessão com usuário logado).",
  script: SCRIPT,
  nodeOptions: [],
  env: [{ name: "JARVIS_SERVICE_MODE", value: "1" }],
});

svc.on("install", () => {
  console.log('Serviço "JARVIS Agente Local" instalado. Iniciando...');
  svc.start();
});
svc.on("alreadyinstalled", () => console.log("Serviço já estava instalado."));
svc.on("start", () => console.log("Serviço iniciado. Veja o status em services.msc."));
svc.on("error", (err) => {
  console.error("Falha ao instalar o serviço:", err?.message || err);
  process.exitCode = 1;
});

svc.install();
