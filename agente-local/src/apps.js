/**
 * Registro de aplicativos do PC — resolve "abre o navegador" para um executável.
 *
 * ---------------------------------------------------------------------------
 * O QUE FALTAVA
 *
 * O comando `open` do agente abre CAMINHO ou URL. Não resolve nome: "abre o
 * navegador" não funcionava, porque ninguém sabia que "navegador" é o Brave
 * deste PC. Este módulo é essa tradução, e nada além dela.
 *
 * ---------------------------------------------------------------------------
 * A CONTENÇÃO, QUE É O PONTO
 *
 * Só roda o que está NO MAPA. O mapa é construído aqui, no PC, varrendo pastas
 * conhecidas — nunca vem da rede. Isso importa porque a diferença entre "abrir
 * um app" e "executar um binário arbitrário" é exatamente essa: um caminho que
 * chega pelo WebSocket não vira processo por este caminho, em nenhuma hipótese.
 *
 * E mesmo dentro do mapa há uma segunda cerca: `EXIGEM_CONFIRMACAO`. Abrir o
 * Spotify e abrir o `powershell.exe` não são o mesmo pedido, ainda que os dois
 * sejam "um app instalado". Quem der de cara com um shell, um editor de
 * registro ou um agendador de tarefas pergunta antes — é a Seção 6 aplicada a
 * um verbo novo.
 */
import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { leJsonConfig } from "./json-config.js";

function baseDir() {
  return process.env.JARVIS_AGENT_DIR || path.join(os.homedir(), ".jarvis-agente");
}
function arquivo() { return path.join(baseDir(), "apps.json"); }

/* Apelidos curados. Vêm de um app anterior do Victor (VTZ 1.11), onde já tinham
   sido lapidados no uso — "navegador" e "browser" apontando pros três
   navegadores é o tipo de coisa que só aparece usando. O scanner completa o
   resto sozinho; esta tabela existe pra os casos que ele erraria (o executável
   do VS Code se chama `code`, o do Edge `msedge`). */
export const ALIASES_CURADOS = {
  brave: ["brave", "navegador", "browser"],
  chrome: ["chrome", "google chrome", "navegador", "browser"],
  firefox: ["firefox", "mozilla", "navegador", "browser"],
  msedge: ["edge", "microsoft edge", "navegador", "browser"],
  code: ["vscode", "visual studio code", "vs code", "editor"],
  discord: ["discord"],
  spotify: ["spotify", "musica", "música", "player"],
  whatsapp: ["whatsapp", "wpp", "zap"],
  telegram: ["telegram"],
  steam: ["steam", "jogos"],
  notepad: ["bloco de notas", "notepad", "bloco"],
  explorer: ["explorador", "arquivos", "pastas"],
  calc: ["calculadora", "calc"],
};

/* Está no mapa, mas não é "só um app". Abrir um shell é abrir a porta pra
   qualquer coisa; editor de registro e agendador são persistência. Não estão
   BLOQUEADOS — o Victor pode querer abrir o PowerShell — mas não passam
   sozinhos. */
const EXIGEM_CONFIRMACAO = new Set([
  "cmd", "powershell", "pwsh", "wt", "conhost",
  "regedit", "regedt32", "mmc", "taskschd", "services",
  "wscript", "cscript", "mshta", "rundll32", "psexec",
  "taskmgr", "msconfig", "gpedit", "secpol",
]);

export const precisaConfirmar = (id) => EXIGEM_CONFIRMACAO.has(String(id || "").toLowerCase());

const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/\s+/g, " ").trim();

export function carregaApps() {
  const d = leJsonConfig(arquivo());
  return d && typeof d === "object" ? d : {};
}

export function salvaApps(mapa) {
  fs.mkdirSync(baseDir(), { recursive: true });
  fs.writeFileSync(arquivo(), JSON.stringify(mapa, null, 2), { mode: 0o600 });
  return mapa;
}

/**
 * Acha o app por id ou apelido. Devolve `{ id, exe, aliases }` ou null.
 *
 * Compara normalizado (sem acento, minúsculo) porque quem fala "musica" e quem
 * fala "música" quer a mesma coisa, e a transcrição do whisper erra acento com
 * frequência.
 */
export function resolveApp(nome, mapa = carregaApps()) {
  const alvo = norm(nome);
  if (!alvo) return null;
  if (mapa[alvo]) return { id: alvo, ...mapa[alvo] };
  for (const [id, info] of Object.entries(mapa)) {
    if (norm(id) === alvo) return { id, ...info };
    if ((info.aliases || []).some((a) => norm(a) === alvo)) return { id, ...info };
  }
  return null;
}

/* Onde procurar. Profundidade 2 (pasta + subpastas diretas) de propósito: o
   .exe de quase todo programa está num desses dois níveis, e varrer o disco
   inteiro levaria minutos pra achar as mesmas coisas. */
const RAIZES = () => {
  const u = os.homedir();
  return [
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    path.join(u, "AppData", "Local", "Programs"),
    path.join(u, "AppData", "Local"),
    path.join(u, "AppData", "Roaming"),
    "C:\\Windows\\System32",
  ];
};

/* Ruído: instaladores, desinstaladores e utilitários que ninguém pede por
   nome. Sem este filtro o mapa vira 4 mil entradas e "abre o editor" fica
   ambíguo. */
const IGNORAR = /(unins|setup|install|update|crash|report|helper|service|daemon|elevat|redist|vcredist|dotnet)/i;

function exesDe(dir, profundidade) {
  const achados = [];
  let entradas;
  try {
    entradas = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return achados;   // sem permissão é normal em Program Files
  }
  for (const e of entradas) {
    const p = path.join(dir, e.name);
    if (e.isFile() && e.name.toLowerCase().endsWith(".exe") && !IGNORAR.test(e.name)) {
      achados.push(p);
    } else if (e.isDirectory() && profundidade > 0 && !IGNORAR.test(e.name)) {
      achados.push(...exesDe(p, profundidade - 1));
    }
  }
  return achados;
}

/**
 * Varre o PC e monta o mapa. Preserva o que já existia: se o usuário editou os
 * apelidos à mão, uma varredura nova não pode apagar o trabalho dele.
 */
export function varreApps({ raizes = RAIZES(), mapaAtual = carregaApps() } = {}) {
  const mapa = { ...mapaAtual };
  for (const raiz of raizes) {
    for (const exe of exesDe(raiz, 2)) {
      const id = norm(path.basename(exe, ".exe"));
      if (!id || id.length < 2) continue;
      /* Primeiro caminho encontrado vence: as raízes estão em ordem de
         preferência, e reescrever com o segundo trocaria um app que funciona
         por um homônimo em AppData. */
      if (mapa[id]?.exe && fs.existsSync(mapa[id].exe)) continue;
      mapa[id] = {
        exe,
        aliases: [...new Set([...(mapa[id]?.aliases || []), ...(ALIASES_CURADOS[id] || [])])],
      };
    }
  }
  /* Curados que a varredura não achou continuam valendo como apelido de quem
     achou — senão "navegador" só funcionaria se TODOS os navegadores
     estivessem instalados. */
  for (const [id, aliases] of Object.entries(ALIASES_CURADOS)) {
    if (mapa[id]) mapa[id].aliases = [...new Set([...(mapa[id].aliases || []), ...aliases])];
  }
  return salvaApps(mapa);
}

/**
 * Sobe o app. `detached` porque o agente não é dono da janela: fechar o JARVIS
 * não pode levar junto o Chrome que ele abriu.
 *
 * Espera o evento `spawn` em vez de retornar na hora. O `spawn()` do Node NÃO
 * lança quando o executável não existe — ele emite `error` depois, de forma
 * assíncrona. A primeira versão daqui tinha só um try/catch e por isso
 * respondia "abri" para um caminho que não existia: o agente declarava vitória
 * sobre uma falha, que é o defeito que este projeto mais persegue. Foi um teste
 * com um .exe falso que expôs.
 */
export function abreApp(entrada) {
  return new Promise((resolve) => {
    let p;
    try {
      p = spawn(entrada.exe, [], { detached: true, stdio: "ignore", windowsHide: false });
    } catch (e) {
      return resolve({ ok: false, erro: String(e.message).slice(0, 200) });
    }
    let respondeu = false;
    const uma = (r) => { if (!respondeu) { respondeu = true; resolve(r); } };
    p.once("error", (e) => uma({ ok: false, erro: String(e.message).slice(0, 200) }));
    p.once("spawn", () => { p.unref(); uma({ ok: true }); });
  });
}

/** Fecha pelo nome da imagem. `/T` leva os filhos; sem ele, um navegador
 *  fecha a janela e deixa os processos de aba vivos. */
export function fechaApp(entrada) {
  const imagem = path.basename(entrada.exe);
  return new Promise((resolve) => {
    if (process.platform !== "win32") return resolve({ ok: false, erro: "só no Windows" });
    execFile("taskkill", ["/IM", imagem, "/T", "/F"], { shell: false, timeout: 10000, windowsHide: true },
      (err, stdout, stderr) => {
        if (!err) return resolve({ ok: true });
        const saida = String(stderr || stdout || err.message);
        /* "não encontrado" não é falha: pedir pra fechar o que já está fechado
           é o estado desejado, e tratar como erro faria um macro inteiro
           parecer quebrado por causa de um app que nem estava aberto. */
        if (/not found|nao encontrado|não encontrado|128/i.test(saida)) {
          return resolve({ ok: true, jaEstavaFechado: true });
        }
        resolve({ ok: false, erro: saida.slice(0, 200) });
      });
  });
}
