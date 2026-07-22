#!/usr/bin/env node
/**
 * Fluxo de pareamento no terminal (`npm run pair`). É o "abre e mostra um
 * código tipo WXYZ-2345" da Seção 3 — só que numa janela de terminal em vez
 * de uma janela gráfica (o núcleo é o mesmo pairWithBackend() de pairing.js,
 * já testado contra o backend real).
 *
 * Aceita JARVIS_BACKEND_URL / JARVIS_AGENT_NAME por env var pra rodar sem
 * prompt interativo (scripts, instalador silencioso).
 */
import os from "node:os";
import readline from "node:readline";
import { pairWithBackend } from "./pairing.js";
import { saveToken } from "./token-vault.js";
import { saveConfig, loadConfig } from "./config.js";

function ask(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (answer) => { rl.close(); resolve(answer); }));
}

async function main() {
  const existing = loadConfig();
  if (existing && !process.env.JARVIS_BACKEND_URL) {
    const answer = await ask(`Já pareado como "${existing.name}" em ${existing.backendUrl}. Parear de novo? (s/N) `);
    if (!/^s/i.test(answer.trim())) {
      console.log("Cancelado.");
      return;
    }
  }

  const backendUrl = (process.env.JARVIS_BACKEND_URL || await ask("URL do backend (ex.: https://meu-servidor.onrender.com): ")).trim();
  if (!backendUrl) throw new Error("URL do backend é obrigatória.");
  const name = (process.env.JARVIS_AGENT_NAME || await ask(`Nome deste dispositivo [${os.hostname()}]: `)).trim() || os.hostname();
  const platform = os.platform();

  console.log("\nIniciando pareamento...\n");
  const result = await pairWithBackend({
    backendUrl,
    name,
    platform,
    onEvent: (evt) => {
      if (evt.type === "code") {
        const line = "=".repeat(28);
        console.log(line);
        console.log(`  Código: ${evt.userCode}`);
        console.log(line);
        console.log('\nNo JARVIS (navegador), abra "Parear dispositivo" e digite o código acima.');
        console.log(`Expira em ${Math.round(evt.expiresIn / 60)} minutos.\n`);
      } else if (evt.type === "pending") {
        process.stdout.write(".");
      } else if (evt.type === "slow_down") {
        process.stdout.write("~");
      }
    },
  });

  await saveToken(result.agentToken); // cofre do SO — lança se indisponível (de propósito, ver token-vault.js)
  saveConfig({ agentId: result.agentId, backendUrl, name, platform, allowedRoots: result.allowedRoots });

  console.log(`\n\nPareado com sucesso — agent_id: ${result.agentId}`);
  console.log("Token salvo no cofre de credenciais do sistema.");
  console.log('Rode "npm start" pra conectar o agente.');
}

main().catch((err) => {
  console.error("\nFalha no pareamento:", err.message);
  process.exitCode = 1;
});
