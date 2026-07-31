/**
 * Sobe o backend Python de verdade pros testes de integração, e conversa com
 * ele por HTTP de um jeito que não quebra por acaso.
 *
 * Por que existe:
 *
 * 1. `--timeout-keep-alive`. O uvicorn fecha conexão ociosa em 5s (padrão).
 *    O `fetch` do Node reaproveita socket do pool: se o teste pausa (esperar o
 *    WS abrir, esperar um poll) e a próxima requisição pega justo o socket que
 *    o servidor acabou de fechar, o Node estoura `TypeError: fetch failed` —
 *    sem bug nenhum no código. É corrida de relógio, então falha só às vezes e
 *    só onde tudo é mais lento (bateu no CI do Windows, nunca aqui no Linux).
 *    Subir o keep-alive tira a janela da corrida.
 *
 * 2. `fetchTeimoso`. Cinto e suspensório pro que sobrar: erro de REDE (não de
 *    HTTP) tenta de novo, o que abre socket novo. Status 4xx/5xx passa direto —
 *    esses são resposta do servidor, e é isso que os testes querem medir.
 *
 * O código de produção já lida com isso sozinho (ver o contador de falhas de
 * rede no poll do pairing.js) — quem estava frágil era só o teste.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { PYTHON_BIN } from "./_python.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

/** Sobe uvicorn numa porta, com banco temporário isolado. Devolve o processo. */
export function sobeBackend({ port, token }) {
  const dbPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-int-")), "test.db");
  return spawn(
    PYTHON_BIN,
    [
      "-m", "uvicorn", "app.main:app",
      "--host", "127.0.0.1",
      "--port", String(port),
      "--timeout-keep-alive", "120",
    ],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, BACKEND_TOKEN: token, JARVIS_DB_PATH: dbPath },
      stdio: "ignore",
    }
  );
}

/** Espera o /api/health responder. Estoura com mensagem clara em vez de travar. */
export async function esperaSaude(base, tentativas = 60) {
  for (let i = 0; i < tentativas; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) return;
    } catch {
      /* ainda subindo */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`backend não respondeu em ${base}/api/health a tempo`);
}

/** fetch que insiste em falha de REDE. Resposta HTTP, mesmo 500, volta como está. */
export async function fetchTeimoso(url, opts, tentativas = 3) {
  let ultimo;
  for (let i = 0; i < tentativas; i++) {
    try {
      return await fetch(url, opts);
    } catch (err) {
      ultimo = err;
      await new Promise((r) => setTimeout(r, 150 * (i + 1)));
    }
  }
  throw ultimo;
}
