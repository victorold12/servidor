/* Gerente de residência do modelo local.
 *
 * O QUE ESTE TESTE PROTEGE
 *
 * A GPU desta máquina não cabe tudo, e quem cede é o modelo — porque a voz
 * falha em SILÊNCIO quando perde e o modelo só cai na nuvem. Todo o valor do
 * módulo está em não mentir sobre o estado da memória: dizer "a GPU está livre"
 * sem ter conferido faria o Chatterbox subir, atender na 8004 e não falar,
 * exatamente o defeito que o módulo existe pra evitar.
 *
 * Por isso o caso central aqui não é o caminho feliz — é o `cedeGpu` quando a
 * consulta FALHA. "Não sei" tem que continuar sendo "não sei" até o chamador.
 *
 * Sobe um Ollama de mentira em porta pedida ao sistema (nunca cravada: o
 * `node --test` roda arquivos em paralelo, e porta fixa já custou dois builds).
 */
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

/* Estado que cada teste molda antes de chamar o módulo. */
let tags, ps, statusPs, recusaDescarregar;
const descarregados = [];

function reset() {
  tags = { models: [] };
  ps = { models: [] };
  statusPs = 200;
  recusaDescarregar = new Set();
  descarregados.length = 0;
}
reset();

const servidor = http.createServer((req, res) => {
  const responde = (codigo, corpo) => {
    res.writeHead(codigo, { "Content-Type": "application/json" });
    res.end(JSON.stringify(corpo));
  };
  if (req.url === "/api/tags") return responde(200, tags);
  if (req.url === "/api/ps") return responde(statusPs, ps);
  if (req.url === "/api/generate") {
    let corpo = "";
    req.on("data", (c) => { corpo += c; });
    req.on("end", () => {
      const j = JSON.parse(corpo || "{}");
      if (j.keep_alive === 0) descarregados.push(j.model);
      if (recusaDescarregar.has(j.model)) return responde(500, { error: "ocupado" });
      responde(200, { done: true });
    });
    return;
  }
  responde(404, {});
});

await new Promise((r) => servidor.listen(0, "127.0.0.1", r));
process.env.JARVIS_OLLAMA_BASE = `http://127.0.0.1:${servidor.address().port}`;

const ollama = await import("../src/ollama.js");

test.after(() => servidor.close());

const GiB = 1024 ** 3;
const MODELOS = {
  models: [
    { name: "qwen2.5:3b", size: 1.8 * GiB, capabilities: ["completion", "tools"],
      details: { parameter_size: "3.1B", quantization_level: "Q4_K_M" } },
    { name: "qwen3.5:9b", size: 6.14 * GiB, capabilities: ["completion", "tools", "vision"],
      details: { parameter_size: "9.7B", quantization_level: "Q4_K_M" } },
    { name: "tagarela:1b", size: 0.9 * GiB, capabilities: ["completion"],
      details: { parameter_size: "1B", quantization_level: "Q4_0" } },
  ],
};

test("porta aberta não basta: Ollama sem modelo é Ollama inútil", async () => {
  reset();
  const r = await ollama.disponivel();
  assert.equal(r.ok, false, "no ar sem modelo nenhum não é 'disponível'");
  assert.match(r.motivo, /sem nenhum modelo/,
    "tem que dizer QUAL é o problema, senão manda investigar rede à toa");
  assert.match(r.motivo, /ollama pull/, "e dizer como resolver");

  tags = MODELOS;
  assert.equal((await ollama.disponivel()).ok, true);
});

test("serviço parado é diagnosticado como parado, não como erro de rede", async () => {
  const antes = process.env.JARVIS_OLLAMA_BASE;
  process.env.JARVIS_OLLAMA_BASE = "http://127.0.0.1:1";   // ninguém atende aqui
  try {
    const r = await ollama.disponivel();
    assert.equal(r.ok, false);
    assert.match(r.motivo, /não está rodando|ollama serve/,
      "confundir 'parado' com 'rede ruim' manda caçar o problema errado");
  } finally {
    process.env.JARVIS_OLLAMA_BASE = antes;
  }
});

test("residentes LEVANTA quando não dá pra consultar (não devolve lista vazia)", async () => {
  reset();
  statusPs = 500;
  await assert.rejects(() => ollama.residentes(), /500/,
    "lista vazia significaria 'nada carregado' — o oposto de 'não consegui olhar'");
});

test("cedeGpu distingue 'já estava livre' de 'não sei'", async () => {
  reset();
  tags = MODELOS;

  /* Caso 1: consultou e não havia nada. */
  const livre = await ollama.cedeGpu();
  assert.equal(livre.ok, true);
  assert.deepEqual(livre.soltos, []);
  assert.match(livre.motivo, /já estava livre/);

  /* Caso 2: NÃO conseguiu consultar. Aqui está o coração do módulo: este
     resultado não pode ser confundido com o de cima, senão a voz sobe achando
     que tem GPU e falha calada. */
  statusPs = 500;
  const naoSei = await ollama.cedeGpu();
  assert.equal(naoSei.ok, false, "não conferir NUNCA pode virar 'está livre'");
  assert.deepEqual(naoSei.soltos, []);
  assert.match(naoSei.motivo, /não deu pra saber/);
});

test("cedeGpu solta o que está carregado e diz o que soltou", async () => {
  reset();
  tags = MODELOS;
  ps = { models: [
    { name: "qwen3.5:9b", size: 6.14 * GiB, size_vram: 4 * GiB },
    { name: "qwen2.5:3b", size: 1.8 * GiB, size_vram: 1.8 * GiB },
  ] };

  const r = await ollama.cedeGpu();
  assert.equal(r.ok, true);
  assert.deepEqual(r.soltos.sort(), ["qwen2.5:3b", "qwen3.5:9b"]);
  assert.deepEqual(descarregados.sort(), ["qwen2.5:3b", "qwen3.5:9b"],
    "descarregar é keep_alive:0 — o Ollama não tem rota de unload");
});

test("um modelo que recusa sair não vira sucesso, e não impede os outros", async () => {
  reset();
  tags = MODELOS;
  ps = { models: [
    { name: "teimoso:7b", size: 4 * GiB, size_vram: 4 * GiB },
    { name: "qwen2.5:3b", size: 1.8 * GiB, size_vram: 1.8 * GiB },
  ] };
  recusaDescarregar.add("teimoso:7b");

  const r = await ollama.cedeGpu();
  assert.equal(r.ok, false, "sobrou modelo na GPU: a voz não tem folga garantida");
  assert.deepEqual(r.soltos, ["qwen2.5:3b"], "o que deu pra soltar foi solto");
  assert.deepEqual(r.resistiram, ["teimoso:7b"]);
  assert.match(r.motivo, /teimoso/, "tem que nomear quem ficou");
});

test("residentes marca quando o modelo escorreu pra RAM", async () => {
  reset();
  ps = { models: [{ name: "grande:9b", size: 6 * GiB, size_vram: 4 * GiB }] };
  const [m] = await ollama.residentes();
  assert.equal(m.soNaGpu, false, "size_vram < size é o sintoma de orçamento estourado");

  ps = { models: [{ name: "certo:3b", size: 2 * GiB, size_vram: 2 * GiB }] };
  assert.equal((await ollama.residentes())[0].soNaGpu, true);
});

test("escolhe pega o MAIOR que cabe depois de reservar a voz", async () => {
  reset();
  tags = MODELOS;
  /* 8 GiB livres - 2,5 de reserva = 5,5 de orçamento: o 9B (6,14) não cabe,
     o 3B (1,8) cabe e é o maior que cabe. */
  const r = await ollama.escolhe({ livreBytes: 8 * GiB });
  assert.equal(r.nome, "qwen2.5:3b");
  assert.equal(r.cabeNaGpu, true);
});

test("com VRAM de sobra, o maior ganha", async () => {
  reset();
  tags = MODELOS;
  const r = await ollama.escolhe({ livreBytes: 24 * GiB });
  assert.equal(r.nome, "qwen3.5:9b", "modelo maior responde melhor; o teto é o espaço");
});

test("a reserva da voz é intocável", async () => {
  reset();
  tags = MODELOS;
  /* 3 GiB livres: sem reserva o 1B caberia. Com os 2,5 reservados, sobra 0,5 e
     nada cabe — e é assim que tem que ser, porque a voz vem primeiro. */
  const r = await ollama.escolhe({ livreBytes: 3 * GiB });
  assert.equal(r.cabeNaGpu, false);
  assert.match(r.motivo, /CPU/, "tem que avisar que vai rodar lento, não fingir que cabe");
});

test("VRAM que não dá pra medir escolhe o menor (o erro barato)", async () => {
  reset();
  tags = MODELOS;
  const r = await ollama.escolhe({ livreBytes: null });
  assert.equal(r.nome, "tagarela:1b", "sem saber o espaço, o menor é quem erra mais barato");
  assert.equal(r.cabeNaGpu, null, "null é 'não sei', diferente de false que é 'não cabe'");
  assert.match(r.motivo, /não deu pra medir/);
});

test("modelo sem suporte a ferramentas é filtrado quando o JARVIS precisa agir", async () => {
  reset();
  tags = MODELOS;
  /* O tagarela:1b é o menor, mas não tem `tools`: escolhê-lo faria o JARVIS
     responder texto onde deveria chamar o Agente Local. */
  const r = await ollama.escolhe({ livreBytes: null, precisaFerramentas: true });
  assert.equal(r.nome, "qwen2.5:3b");
  assert.ok(r.ferramentas);
});

test("sem nenhum modelo, escolhe devolve null em vez de inventar", async () => {
  reset();
  assert.equal(await ollama.escolhe({ livreBytes: 8 * GiB }), null);
});

test("vramLivreBytes devolve null quando não dá pra medir, nunca zero", async () => {
  /* Numa máquina sem nvidia-smi o valor é null. Numa com, é um número > 0.
     O que NÃO pode acontecer é virar 0: zero bloquearia o local numa máquina
     que funciona. */
  const v = await ollama.vramLivreBytes();
  assert.ok(v === null || v > 0, `esperava null ou >0, veio ${v}`);
});

test("resumo não quebra quando /api/ps está fora", async () => {
  reset();
  tags = MODELOS;
  statusPs = 500;
  const r = await ollama.resumo();
  assert.equal(r.ok, true, "o resumo ainda serve: dá pra listar modelos");
  assert.equal(r.residentes, null,
    "null é 'não consegui consultar'; [] seria 'nada carregado' e é mentira diferente");
});
