#!/usr/bin/env node
/**
 * O ÚLTIMO DEGRAU: prova que sai SOM.
 *
 * ---------------------------------------------------------------------------
 * POR QUE ESTE ARQUIVO EXISTE
 *
 * Este projeto subiu a mesma escada quatro vezes, e em cada degrau achou que
 * tinha chegado:
 *
 *   | critério                      | por que era mentira                     |
 *   |-------------------------------|-----------------------------------------|
 *   | "o `pip` terminou com 0"      | o torch estava corrompido no disco      |
 *   | "a porta 8004 respondeu"      | o modelo falhou ao carregar             |
 *   | "o modelo carregou"           | ninguém tinha pedido uma frase          |
 *   | "saiu um arquivo"             | podia ser um .wav de silêncio           |
 *
 * Aqui o critério é o último: um arquivo de áudio com cabeçalho RIFF válido,
 * duração plausível para a frase, e amplitude diferente de zero. Silêncio
 * perfeito reprova — é exatamente o que um motor meio-quebrado produz.
 *
 * ---------------------------------------------------------------------------
 * POR QUE USA O CLIENTE DO AGENTE, E NÃO UM fetch PRÓPRIO
 *
 * `speak()` do `agente-local/src/tts.js` é o que roda quando o JARVIS fala de
 * verdade — com a mesma degradação (Chatterbox → Kokoro → nada) e a mesma
 * leitura de configuração. Um `fetch` escrito aqui provaria que *existe* um
 * jeito de arrancar áudio do servidor, não que o caminho do usuário funciona.
 * Foi essa distinção que faltou nas três validações anteriores.
 *
 * Uso: node scripts/prova-voz.js ["frase"] [segundos-de-espera]
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { ligaMotores, motoresEmDisco, paraMotores, portaRespondendo, raizDasVozes } from "../src/instalador-vozes.js";

const FRASE = process.argv[2] || "Olá, senhor. Sistemas operando normalmente.";
const ESPERA = Number(process.argv[3] || 420) * 1000;
const documentos = process.env.JARVIS_DOCUMENTOS || path.join(os.homedir(), "Documents");

/* Os mesmos sinais que o sobe-vozes.js vigia: o servidor grita quando o modelo
   morre, e ler o que ele grita é mais honesto que confiar no socket. */
const MODELO_MORTO = [
  /TTS Model failed to load/i,
  /Failed to load model/i,
  /object is not callable/i,
];

const dito = [];
const log = (s) => console.log(s);

console.log(`raiz: ${raizDasVozes(documentos)}`);
console.log(`frase: "${FRASE}"\n`);

/* O alvo vem do DISCO, não da lista do que subiu agora. `ligaMotores` pula
   motor que já está no ar (o atalho da Inicialização sobe no login, e uma
   execução anterior pode ter deixado o processo vivo) — e nesse caso ele
   devolve lista vazia. Tratar isso como "nenhum motor subiu" era desistir
   justamente quando estava tudo pronto. */
const instalados = motoresEmDisco(documentos).filter((m) => m.instalado);
if (!instalados.length) {
  console.error("\nNenhum motor instalado. Rode antes: node scripts/diagnostico-vozes.js");
  process.exit(1);
}

const vivos = await ligaMotores({
  documentos,
  aoLinha: (l) => { dito.push(l); log(l); },
});

/* Espera a porta. O Chatterbox carrega ~4 GB antes de atender, então perguntar
   uma vez e desistir reprovaria uma instalação boa. */
const alvo = instalados[0];
/* Só existe processo filho pra vigiar se fomos NÓS que subimos. Quando ele já
   estava no ar, não há exitCode pra consultar — e é certo não matar no fim algo
   que não foi este script que ligou. */
const filhoDoAlvo = vivos.find((v) => v.id === alvo.id)?.filho || null;
const inicio = Date.now();
let atendeu = false;
while (!atendeu && Date.now() - inicio < ESPERA) {
  if (filhoDoAlvo && filhoDoAlvo.exitCode !== null) {
    console.error(`\n[${alvo.nome}] morreu (código ${filhoDoAlvo.exitCode}) antes de atender.`);
    process.exit(1);
  }
  atendeu = await portaRespondendo(alvo.porta, 1000);
  if (!atendeu) await new Promise((r) => setTimeout(r, 3000));
}
if (!atendeu) {
  console.error(`\n[${alvo.nome}] não respondeu na porta ${alvo.porta} em ${ESPERA / 1000}s.`);
  paraMotores(vivos);
  process.exit(1);
}
console.log(`\n[${alvo.nome}] respondeu na porta ${alvo.porta} depois de ${Math.round((Date.now() - inicio) / 1000)}s.`);

if (dito.some((l) => MODELO_MORTO.some((re) => re.test(l)))) {
  console.error(`[${alvo.nome}] a porta abriu MAS o modelo não carregou — responderia sem falar.`);
  paraMotores(vivos);
  process.exit(1);
}

/* O cliente real do agente. Import dinâmico com file:// porque o agente-local é
   repo irmão e o caminho tem espaço e letra de unidade no Windows.

   `fileURLToPath`, NUNCA `new URL(...).pathname`: o pathname devolve
   "/C:/Users/VTz%20produti/..." — com a unidade colada na barra e o espaço
   percent-encoded. O caminho resultante vira "VTz%20produti" e não existe.
   Está documentado em scripts/prepare-webapp.js, que já pagou por isso, e eu
   repeti o erro assim mesmo. */
const raizAgente = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "agente-local");
const { speak } = await import(pathToFileURL(path.join(raizAgente, "src", "tts.js")).href);

/* ===== A PORTA ABRE ANTES DO MODELO FICAR PRONTO =====
   O servidor liga o uvicorn e SÓ ENTÃO baixa/carrega os pesos. Nessa janela ele
   responde 503 ("TTS engine model is not currently loaded"). Pedir a frase uma
   vez e desistir reprovaria uma instalação boa — foi o que aconteceu aqui, e é
   a mesma armadilha que este arquivo existe pra combater, um nível acima.

   Então insiste até o orçamento acabar, e imprime o que cada tentativa disse:
   sem `tried`, "nenhum motor respondeu" esconde o 503 que explicaria tudo. */
console.log("\npedindo a frase ao motor (insiste enquanto o modelo carrega)...");
let r = null;
const limiteFala = Date.now() + ESPERA;
let ultimoAviso = "";
while (Date.now() < limiteFala) {
  try {
    r = await speak(FRASE);
  } catch (e) {
    r = { ok: false, reason: "speak() estourou: " + e.message };
  }
  if (r?.ok && r.audio) break;

  const detalhe = (r?.tried || []).map((t) => `${t.engine}: ${t.erro}`).join(" | ")
    || r?.reason || "sem motivo";
  if (detalhe !== ultimoAviso) {
    console.log(`  ainda não: ${detalhe}`);
    ultimoAviso = detalhe;
  }
  if (filhoDoAlvo && filhoDoAlvo.exitCode !== null) {
    console.error(`\n[${alvo.nome}] morreu (código ${filhoDoAlvo.exitCode}) enquanto eu pedia a frase.`);
    break;
  }
  await new Promise((res) => setTimeout(res, 5000));
}

if (!r || r.ok === false || !r.audio) {
  console.error("\nnão veio áudio:", r?.reason || r?.error || "(sem resposta)");
  for (const t of r?.tried || []) console.error(`  ${t.engine}: ${t.erro}`);
  if (r?.hint) console.error(`  dica: ${r.hint}`);
  paraMotores(vivos);
  process.exit(1);
}

const bytes = Buffer.isBuffer(r.audio) ? r.audio : Buffer.from(r.audio);
const saida = path.join(raizDasVozes(documentos), "prova-voz.wav");
fs.writeFileSync(saida, bytes);

/* ===== A parte que separa "saiu arquivo" de "saiu som" ===== */
const problemas = [];
if (bytes.length < 8000) problemas.push(`só ${bytes.length} bytes`);
if (bytes.slice(0, 4).toString("ascii") !== "RIFF") problemas.push("sem cabeçalho RIFF (não é wav)");

let segundos = null;
let pico = null;
if (bytes.length > 44 && bytes.slice(0, 4).toString("ascii") === "RIFF") {
  const canais = bytes.readUInt16LE(22);
  const taxa = bytes.readUInt32LE(24);
  const bits = bytes.readUInt16LE(34);
  const dados = bytes.length - 44;
  if (taxa > 0 && canais > 0 && bits > 0) segundos = dados / (taxa * canais * (bits / 8));

  /* Amplitude: um motor meio-quebrado devolve um wav perfeito e MUDO, e isso
     passaria em tamanho e cabeçalho. Amostra o meio do arquivo, onde a fala
     está — o começo costuma ser silêncio legítimo. */
  if (bits === 16) {
    let max = 0;
    for (let i = Math.floor(44 + dados / 3); i + 1 < bytes.length; i += 2) {
      max = Math.max(max, Math.abs(bytes.readInt16LE(i)));
    }
    pico = max;
    if (max < 200) problemas.push(`silêncio (pico ${max} de 32767)`);
  }
  if (segundos !== null && segundos < 0.4) problemas.push(`duração de só ${segundos.toFixed(2)}s`);
}

console.log("\n=== veredito ===");
console.log(`  motor:    ${r.engine}${r.fallback ? " (fallback)" : ""}`);
console.log(`  arquivo:  ${saida}`);
console.log(`  bytes:    ${bytes.length.toLocaleString("pt-BR")}`);
if (segundos !== null) console.log(`  duração:  ${segundos.toFixed(2)}s`);
if (pico !== null) console.log(`  pico:     ${pico} de 32767`);

paraMotores(vivos);

if (problemas.length) {
  console.error(`\nREPROVADO: ${problemas.join("; ")}.`);
  process.exit(1);
}
console.log("\nAPROVADO: saiu som. Abra o arquivo acima e ouça pra confirmar o timbre.");
