/**
 * Sobe o backend Python de verdade pros testes de integração.
 *
 * PORTA SORTEADA PELO SISTEMA, e esse é o ponto principal deste arquivo.
 *
 * Antes cada teste cravava um número: pairing usava 8799 e 8800, ws-client
 * usava 8800 e 8801. O `node --test` roda ARQUIVOS EM PARALELO — então dois
 * uvicorn diferentes tentavam a 8800 ao mesmo tempo. Um ganhava o bind, o
 * outro morria caladinho, e os dois testes seguiam falando com o mesmo
 * servidor sem saber. Ficava de pé por sorte: bastava o teste que perdeu
 * terminar primeiro e chamar `proc.kill()` pra derrubar o servidor DEBAIXO do
 * outro, no meio do pareamento. O sintoma era `fetch failed` num teste que não
 * tinha nada de errado, às vezes, só onde o relógio é diferente (bateu duas
 * vezes no CI do Windows, nunca aqui no Linux).
 *
 * Pedir porta 0 ao sistema mata a classe inteira: não existe número pra
 * colidir, nem quando alguém acrescentar um quinto arquivo de teste amanhã.
 *
 * `--timeout-keep-alive` e `fetchTeimoso` continuam abaixo como cinto e
 * suspensório — não foram a causa (eu achei que fossem, e não eram), mas
 * conexão ociosa reciclada é um jeito real de um teste falhar sem bug, e sai
 * de graça deixar coberto.
 */
import { spawn } from "node:child_process";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { PYTHON_BIN } from "./_python.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

/** Porta livre de verdade, escolhida pelo sistema (listen na 0 e devolve qual saiu). */
function portaLivre() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

/**
 * Sobe uvicorn numa porta livre, com banco temporário isolado, e só devolve
 * depois que o /api/health responde. Quem chama recebe `{ proc, base, port }`.
 */
export async function sobeBackend({ token }) {
  const port = await portaLivre();
  const dbPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-int-")), "test.db");
  const proc = spawn(
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
  const base = `http://127.0.0.1:${port}`;
  /* ===== Matar o uvicorn quando ele NÃO sobe =====
     Sem este try/catch, `esperaSaude` estourava e o processo ficava vivo. O
     `node --test` não termina enquanto houver filho, então UMA falha de
     integração transformava a suíte inteira num processo pendurado.
     Aconteceu: o build do .msi 1.2.0 rodou das 05:57 às 11:57 e foi cancelado
     pelo limite de 6 horas do GitHub — a última linha do log era este teste
     falhando, 15 segundos depois de começar. Seis horas de runner por um
     `kill` que faltava.

     `taskkill /T` no Windows: o uvicorn com --reload ou workers cria netos, e
     `proc.kill()` sozinho derruba só o pai, deixando quem de fato segura a
     porta (e o event loop) de pé. */
  try {
    await esperaSaude(base, proc);
  } catch (err) {
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        proc.kill("SIGKILL");
      }
    } catch { /* já morreu: é o estado desejado */ }
    throw err;
  }
  return { proc, base, port };
}

/**
 * Espera o /api/health responder. Se o processo morrer antes (porta ocupada,
 * import quebrado), desiste na hora com o código de saída — em vez de gastar
 * 15s pra dizer só "não respondeu a tempo".
 */
export async function esperaSaude(base, proc, tentativas = 60) {
  let morreu = null;
  proc?.once("exit", (code) => { morreu = code; });
  for (let i = 0; i < tentativas; i++) {
    if (morreu !== null) throw new Error(`backend morreu antes de subir (saiu com ${morreu}) — ${base}`);
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
