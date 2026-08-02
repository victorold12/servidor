#!/usr/bin/env node
/**
 * Prova que o JARVIS FALA a resposta em vez de LER a formatação dela.
 *
 * O `prova-voz.js` responde "sai som?". Este responde a pergunta seguinte, que
 * é a que o Victor levantou ouvindo: sai som de HUMANO? Ele manda pro motor uma
 * resposta de modelo de verdade — com emoji, negrito, lista, caminho de arquivo
 * e URL — e grava o áudio pra ouvir.
 *
 * A checagem automática cobre só o que dá pra medir sem ouvido: que o texto
 * normalizado não tem marcador de markdown, e que o áudio saiu com amplitude.
 * O resto é o Victor abrindo o arquivo. Um teste que afirmasse "soa natural"
 * estaria mentindo — isso não se mede daqui.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { ligaMotores, motoresEmDisco, paraMotores, portaRespondendo, raizDasVozes } from "../src/instalador-vozes.js";

const documentos = process.env.JARVIS_DOCUMENTOS || path.join(os.homedir(), "Documents");
const ESPERA = Number(process.argv[2] || 480) * 1000;

/* Uma resposta com tudo que aparece de verdade no chat. */
const RESPOSTA = [
  "## ✅ Pronto!",
  "",
  "Instalei **3 apps** (100% ok):",
  "- `chrome` — o navegador",
  "- `code` — o editor",
  "",
  "Salvei em C:\\Users\\VTz produti\\Documents\\prova-voz.wav 🚀",
  "Detalhes em https://exemplo.com/x?y=1",
].join("\n");

const raizAgente = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "agente-local");
const { paraFala } = await import(pathToFileURL(path.join(raizAgente, "src", "fala-natural.js")).href);
const { speak } = await import(pathToFileURL(path.join(raizAgente, "src", "tts.js")).href);

console.log("=== o que o modelo escreve ===");
console.log(RESPOSTA);
const falado = paraFala(RESPOSTA);
console.log("\n=== o que o motor vai receber ===");
console.log(falado);

const sobrou = falado.match(/[*_`#|~]|\[|\]|https?:|[\u{1F000}-\u{1FAFF}]/u);
if (sobrou) {
  console.error(`\nREPROVADO: sobrou formatação no texto falado: ${JSON.stringify(sobrou[0])}`);
  process.exit(1);
}

const instalados = motoresEmDisco(documentos).filter((m) => m.instalado);
if (!instalados.length) {
  console.error("\nNenhum motor instalado. Rode antes: node scripts/diagnostico-vozes.js");
  process.exit(1);
}
const alvo = instalados[0];

const vivos = await ligaMotores({ documentos, aoLinha: (l) => console.log(l) });
const filho = vivos.find((v) => v.id === alvo.id)?.filho || null;

const inicio = Date.now();
let atendeu = false;
while (!atendeu && Date.now() - inicio < ESPERA) {
  if (filho && filho.exitCode !== null) {
    console.error(`\n[${alvo.nome}] morreu (código ${filho.exitCode}) antes de atender.`);
    process.exit(1);
  }
  atendeu = await portaRespondendo(alvo.porta, 1000);
  if (!atendeu) await new Promise((r) => setTimeout(r, 3000));
}
if (!atendeu) {
  console.error(`\n[${alvo.nome}] não respondeu na porta ${alvo.porta}.`);
  paraMotores(vivos);
  process.exit(1);
}

console.log(`\n[${alvo.nome}] no ar. Pedindo a fala…`);
let r = null;
const limite = Date.now() + ESPERA;
while (Date.now() < limite) {
  /* Manda o markdown CRU de propósito: quem tem que normalizar é o `speak`, e
     é justamente isso que este arquivo está provando. Normalizar aqui antes
     testaria a função e não o caminho. */
  r = await speak(RESPOSTA).catch((e) => ({ ok: false, reason: e.message }));
  if (r?.ok && r.audio) break;
  await new Promise((res) => setTimeout(res, 5000));
}

if (!r?.ok || !r.audio) {
  console.error("\nnão veio áudio:", r?.reason || "(sem resposta)");
  for (const t of r?.tried || []) console.error(`  ${t.engine}: ${t.erro}`);
  paraMotores(vivos);
  process.exit(1);
}

const bytes = Buffer.isBuffer(r.audio) ? r.audio : Buffer.from(r.audio);
const saida = path.join(raizDasVozes(documentos), "prova-fala-natural.wav");
fs.writeFileSync(saida, bytes);

let pico = 0;
if (bytes.length > 44 && bytes.slice(0, 4).toString("ascii") === "RIFF" && bytes.readUInt16LE(34) === 16) {
  for (let i = 44; i + 1 < bytes.length; i += 2) pico = Math.max(pico, Math.abs(bytes.readInt16LE(i)));
}

console.log("\n=== veredito ===");
console.log(`  arquivo: ${saida}`);
console.log(`  bytes:   ${bytes.length.toLocaleString("pt-BR")}`);
console.log(`  pico:    ${pico} de 32767`);

paraMotores(vivos);

if (pico < 200) {
  console.error("\nREPROVADO: o áudio saiu mudo.");
  process.exit(1);
}
console.log("\nAPROVADO no que dá pra medir. OUÇA o arquivo — se ele ainda soletrar algo,");
console.log("me diga o trecho exato que eu acrescento a regra.");
