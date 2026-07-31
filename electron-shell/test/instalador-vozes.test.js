/* O que este teste protege, em ordem de quanto dói se quebrar:
 *
 * 1. A LISTA FECHADA de modelos. É o único lugar entre o renderer e um processo
 *    novo no PC de alguém. Se ela deixar passar um caminho relativo, a ponte do
 *    preload vira "rode este arquivo qualquer", que é exatamente o que o gate de
 *    4 camadas (docs/SEGURANCA-AGENTE-LOCAL.md) existe pra impedir.
 * 2. Os .bat ASSADOS existirem e terem cara de .bat. Um build sem eles produz um
 *    app com um botão que promete instalar e não instala — e o erro só aparece
 *    no clique, na máquina do usuário.
 * 3. A raiz bater com a que o .bat calcula sozinho. Se divergirem, o instalador
 *    põe as vozes num lugar e o app as procura noutro. Ninguém acha o defeito
 *    olhando pro código: cada lado está certo isolado.
 * 4. O ponto de entrada ser DETECTADO. O Kokoro nunca foi ligado por ninguém
 *    neste projeto (docs/PROXIMA-FASE.md), então chutar `server.py` pra ele era
 *    apostar — e o sintoma de errar seria "o motor não sobe", sem dizer por quê.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  MODELOS_WHISPER,
  PASTA_INSTALADORES,
  caminhoDoInstalador,
  comoLigar,
  motoresEmDisco,
  nomeDoInstalador,
  portaRespondendo,
  raizDasVozes,
} from "../src/instalador-vozes.js";

/* fileURLToPath, não new URL(...).pathname: no Windows o pathname vem como
   "/D:/a/..." e o path.dirname disso produz caminho inválido. Já mordeu este
   repo uma vez, em scripts/prepare-webapp.js. */
const AQUI = path.dirname(fileURLToPath(import.meta.url));
const WEBAPP = path.join(AQUI, "..", "webapp");
const TEM_ASSADOS = fs.existsSync(path.join(WEBAPP, PASTA_INSTALADORES));

/* Caminho do python do venv no formato do sistema onde o teste roda — o CI
   executa isto em ubuntu E em windows. */
const pythonDoVenv = (pasta) =>
  process.platform === "win32"
    ? path.join(pasta, ".venv", "Scripts", "python.exe")
    : path.join(pasta, ".venv", "bin", "python");

function pastaFalsa(arquivos) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), "voz-teste-"));
  for (const rel of arquivos) {
    const alvo = path.join(raiz, rel);
    fs.mkdirSync(path.dirname(alvo), { recursive: true });
    fs.writeFileSync(alvo, "");
  }
  return raiz;
}

test("modelo fora da lista fechada é recusado", () => {
  for (const veneno of [
    "../../../../Windows/System32/calc",
    "base; calc",
    "instalar-tudo-base",
    "",
    null,
    undefined,
    "BASE",
  ]) {
    assert.throws(
      () => caminhoDoInstalador(WEBAPP, veneno),
      /desconhecido/i,
      `deixou passar: ${JSON.stringify(veneno)}`
    );
  }
});

test("o nome do arquivo não deixa o modelo escapar da pasta", () => {
  /* Cinto e suspensório: mesmo que a lista fechada um dia ganhe um item
     descuidado, o nome montado não pode virar caminho. */
  for (const m of MODELOS_WHISPER) {
    const nome = nomeDoInstalador(m);
    assert.equal(path.basename(nome), nome, `${m} produziu caminho, não nome`);
    assert.match(nome, /^instalar-tudo-[a-z0-9.-]+\.bat$/);
  }
});

test("existe um .bat assado por modelo, com cara de .bat", { skip: !TEM_ASSADOS && "rode npm run prepare-webapp" }, () => {
  for (const m of MODELOS_WHISPER) {
    const p = caminhoDoInstalador(WEBAPP, m);
    const txt = fs.readFileSync(p, "utf-8");
    assert.ok(txt.startsWith("@echo off"), `${m}: não começa como script do Windows`);

    /* CRLF: .bat com quebra de linha do Unix roda torto no cmd — algumas linhas
       simplesmente não executam, e sem erro nenhum. */
    const lfSozinho = (txt.match(/(?<!\r)\n/g) || []).length;
    assert.equal(lfSozinho, 0, `${m}: ${lfSozinho} linha(s) só com LF`);

    /* O modelo escolhido tem que estar DENTRO do arquivo: cinco cópias iguais
       com nomes diferentes passariam em tudo acima e baixariam sempre o mesmo. */
    assert.ok(txt.includes(`ggml-${m}.bin`), `${m}: não baixa o modelo que o nome promete`);

    /* Sem JARVIS_SEM_PAUSA o script para num `pause` esperando tecla — e aqui
       não existe ninguém na frente de um terminal pra apertar. */
    assert.ok(txt.includes("JARVIS_SEM_PAUSA"), `${m}: sem escape de pausa, travaria pra sempre`);
  }
});

test("a raiz é a mesma que o .bat calcula", () => {
  assert.equal(raizDasVozes(path.join("C:", "Users", "v", "Documents")), path.join("C:", "Users", "v", "Documents", "VTz LLM"));
});

test("comoLigar detecta server.py", () => {
  const pasta = pastaFalsa([path.relative(".", pythonDoVenv(".")), "server.py"]);
  const r = comoLigar(pasta, 8004);
  assert.equal(r.instalado, true);
  assert.deepEqual(r.args, ["server.py"]);
});

test("comoLigar cai no uvicorn quando não há server.py", () => {
  const pasta = pastaFalsa([path.relative(".", pythonDoVenv(".")), path.join("api", "src", "main.py")]);
  const r = comoLigar(pasta, 8880);
  assert.equal(r.instalado, true);
  assert.ok(r.args.includes("uvicorn"));
  /* A porta tem que ir no comando: sem ela o uvicorn sobe na 8000 e o painel
     procuraria na 8880 pra sempre. */
  assert.ok(r.args.includes("8880"), "não passou a porta pro uvicorn");
});

test("comoLigar diz POR QUE não dá pra ligar, em vez de só falhar", () => {
  const semVenv = comoLigar(pastaFalsa(["server.py"]), 8004);
  assert.equal(semVenv.instalado, false);
  assert.match(semVenv.motivo, /ambiente virtual/i);

  const semEntrada = comoLigar(pastaFalsa([path.relative(".", pythonDoVenv("."))]), 8004);
  assert.equal(semEntrada.instalado, false);
  assert.match(semEntrada.motivo, /server\.py/);
});

test("os dois motores usam as portas que o painel procura", () => {
  const m = motoresEmDisco(path.join(os.tmpdir(), "nao-existe-de-proposito"));
  assert.deepEqual(
    m.map((x) => [x.id, x.porta]),
    [["chatterbox", 8004], ["kokoro", 8880]]
  );
  /* Pasta inexistente = nada instalado. O contrário (dizer "instalado" e falhar
     no spawn) é o caso que produz log confuso. */
  assert.ok(m.every((x) => x.instalado === false));
});

test("portaRespondendo distingue porta ocupada de porta livre", async () => {
  /* Porta pedida ao sistema, nunca cravada: `node --test` roda arquivos em
     paralelo, e dois testes na mesma porta derrubam o servidor um do outro.
     Já custou dois builds neste projeto. */
  const servidor = net.createServer(() => {});
  await new Promise((r) => servidor.listen(0, "127.0.0.1", r));
  const ocupada = servidor.address().port;
  assert.equal(await portaRespondendo(ocupada), true);

  await new Promise((r) => servidor.close(r));
  /* Agora que fechou, a MESMA porta tem que responder "livre" — comparar duas
     portas diferentes não provaria nada sobre a função. */
  assert.equal(await portaRespondendo(ocupada, 150), false);
});
