/**
 * Gerente de residência do modelo local.
 *
 * ---------------------------------------------------------------------------
 * O PROBLEMA DESTA MÁQUINA
 *
 * A GPU tem 8 GiB. O desktop (navegador, Discord, Steam) já come ~3,5 GiB, e
 * sobra pouco pra TRÊS candidatos que querem o mesmo espaço:
 *
 *   - o modelo de linguagem (2 GiB num 3B, 6 GiB num 9B);
 *   - o Chatterbox, que é a voz do JARVIS;
 *   - o Whisper, que é a escuta.
 *
 * Não cabem todos. Alguém tem que ceder, e a escolha não é arbitrária.
 *
 * ---------------------------------------------------------------------------
 * A ASSIMETRIA QUE DEFINE A POLÍTICA
 *
 * Quando o MODELO perde a GPU, ele cai na nuvem: custa meio centavo, responde
 * igual, e o usuário não percebe. O erro é barato e visível.
 *
 * Quando a VOZ perde, ela falha EM SILÊNCIO. O Chatterbox sobe, atende na porta
 * 8004, devolve 200 — e não fala, porque o modelo dele não coube. Está no
 * CLAUDE.md como uma das armadilhas mais caras já pagas aqui, e é a mesma
 * família de defeito do `whisper-cli` sem DLL: existe, atende, não funciona.
 *
 * Erro barato e ruidoso de um lado; erro caro e mudo do outro. Por isso a regra
 * é fixa e não tem exceção: **QUEM CEDE É O MODELO DE LINGUAGEM**.
 *
 * ---------------------------------------------------------------------------
 * POR QUE "NÃO SEI" É UM VALOR DE PRIMEIRA CLASSE AQUI
 *
 * `vramLivreBytes()` devolve `null` quando não consegue medir — máquina sem GPU
 * NVIDIA, driver ausente, `nvidia-smi` fora do PATH. `null` não é zero e não é
 * infinito: tratar como zero bloquearia o local numa máquina que funciona; como
 * infinito, carregaria um 9B em cima da voz. Diante de "não sei", este módulo
 * escolhe o MENOR modelo — que é a decisão que erra mais barato.
 *
 * A mesma disciplina do `telemetria.py`: "de graça" (0.0) e "não sei" (None)
 * são coisas diferentes, e confundir as duas produz número errado com cara de
 * número certo.
 */
import { execFile } from "node:child_process";

const PADRAO_BASE = "http://127.0.0.1:11434";
const GiB = 1024 ** 3;

/**
 * Quanto de VRAM fica reservado pra voz, sempre.
 *
 * O Chatterbox carrega ~2 GiB. Os 2,5 dão a folga do buffer de áudio e do
 * crescimento do desktop enquanto o app está aberto — sem folga, a conta fecha
 * no papel e estoura na hora em que a pessoa fala.
 */
export const RESERVA_VOZ_BYTES = Math.round(2.5 * GiB);

export function base() {
  return (process.env.JARVIS_OLLAMA_BASE || PADRAO_BASE).replace(/\/+$/, "");
}

async function pede(caminho, opcoes = {}, ms = 4000) {
  return fetch(`${base()}${caminho}`, { signal: AbortSignal.timeout(ms), ...opcoes });
}

/**
 * O Ollama está utilizável? Porta aberta NÃO basta.
 *
 * Um Ollama no ar sem nenhum modelo baixado atende na 11434 e recusa toda
 * chamada de chat. É exatamente o "Chatterbox no ar sem voz instalada" com
 * outra roupa, então a checagem é a mesma: pergunta o que ele TEM, não se ele
 * responde.
 */
export async function disponivel() {
  try {
    const r = await pede("/api/tags", {}, 3000);
    if (!r.ok) return { ok: false, motivo: `respondeu ${r.status}` };
    const lista = (await r.json())?.models || [];
    if (!lista.length) {
      return { ok: false, motivo: "no ar, mas sem nenhum modelo baixado (rode: ollama pull qwen2.5:3b)" };
    }
    return { ok: true, detalhe: `${lista.length} modelo(s) baixado(s)` };
  } catch (e) {
    const msg = String(e?.message || e);
    /* Recusa de conexão é o caso comum e tem conserto óbvio; distinguir isso de
       "demorou" evita mandar a pessoa investigar rede quando o serviço só está
       parado. */
    const parado = /ECONNREFUSED|fetch failed|refus/i.test(msg);
    return { ok: false, motivo: parado ? "não está rodando (abra o Ollama ou rode: ollama serve)" : msg.slice(0, 100) };
  }
}

/** Modelos baixados, com o que interessa pra decidir residência. */
export async function modelos() {
  const r = await pede("/api/tags");
  if (!r.ok) return [];
  const lista = (await r.json())?.models || [];
  return lista.map((m) => {
    const d = m.details || {};
    const caps = m.capabilities || [];
    return {
      nome: m.name,
      bytes: m.size || 0,
      params: d.parameter_size || "",
      quant: d.quantization_level || "",
      /* Ferramentas importa porque um modelo sem `tools` não serve pro JARVIS
         chamar o Agente Local — ele responderia texto onde deveria agir. */
      ferramentas: caps.includes("tools"),
      visao: caps.includes("vision"),
    };
  });
}

/**
 * O que está ocupando memória AGORA, e quanto disso está de fato na GPU.
 *
 * LEVANTA em vez de devolver lista vazia quando a consulta falha. A diferença
 * decide o comportamento do `cedeGpu`: lista vazia significa "não há nada
 * carregado, pode subir a voz", e devolver isso quando na verdade não deu pra
 * OLHAR faria o gerente declarar a GPU livre sem ter conferido — que é o
 * defeito exato que este módulo existe pra impedir.
 */
export async function residentes() {
  const r = await pede("/api/ps");
  if (!r.ok) throw new Error(`/api/ps respondeu ${r.status}`);
  return ((await r.json())?.models || []).map((m) => ({
    nome: m.name,
    bytes: m.size || 0,
    vram: m.size_vram || 0,
    /* `size_vram < size` significa que parte do modelo escorreu pra RAM. Ele
       responde, mas devagar — e é o sintoma de que o orçamento estourou. */
    soNaGpu: (m.size_vram || 0) >= (m.size || 0),
    expira: m.expires_at || null,
  }));
}

/**
 * VRAM livre em bytes, ou `null` quando não dá pra medir.
 *
 * Lê do `nvidia-smi` de propósito. O `Win32_VideoController.AdapterRAM` do WMI
 * é um campo de 32 bits com sinal: ele SATURA em 4 GiB e reporta "4,0 GB" numa
 * placa de 8. Custou uma medição errada nesta mesma sessão — a conta de quanto
 * cabia estava pela metade e parecia certa.
 */
export function vramLivreBytes() {
  return new Promise((resolve) => {
    execFile(
      "nvidia-smi",
      ["--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
      { shell: false, timeout: 5000, windowsHide: true },
      (err, stdout) => {
        if (err) return resolve(null);
        const linha = String(stdout || "").trim().split(/\r?\n/)[0] || "";
        const [total, usado] = linha.split(",").map((s) => Number(String(s).trim()));
        if (!Number.isFinite(total) || !Number.isFinite(usado)) return resolve(null);
        resolve(Math.max(0, total - usado) * 1024 * 1024);   // MiB -> bytes
      },
    );
  });
}

/**
 * Qual modelo usar agora, dado o espaço que sobra depois de reservar a voz.
 *
 * Prefere o MAIOR que caiba: modelo maior responde melhor, e o roteador só
 * manda pergunta simples pra cá — então o teto é o espaço, não a dificuldade.
 */
export async function escolhe({ precisaFerramentas = false, reserva = RESERVA_VOZ_BYTES,
                               livreBytes } = {}) {
  const lista = (await modelos()).filter((m) => !precisaFerramentas || m.ferramentas);
  if (!lista.length) return null;

  const porTamanho = [...lista].sort((a, b) => b.bytes - a.bytes);
  const menor = porTamanho[porTamanho.length - 1];
  /* `livreBytes` existe pro teste poder fixar o orçamento: medir de verdade
     depende de `nvidia-smi`, que varia com o que estiver aberto e não existe no
     CI. Produção omite e mede. */
  const livre = livreBytes === undefined ? await vramLivreBytes() : livreBytes;

  if (livre === null) {
    /* Ver o cabeçalho: diante de "não sei", escolher o menor é o erro barato. */
    return { ...menor, cabeNaGpu: null,
      motivo: "não deu pra medir a VRAM; escolhi o menor por segurança" };
  }

  const orcamento = Math.max(0, livre - reserva);
  const cabe = porTamanho.find((m) => m.bytes <= orcamento);
  if (cabe) {
    return { ...cabe, cabeNaGpu: true,
      motivo: `cabe nos ${(orcamento / GiB).toFixed(1)} GiB livres depois de reservar a voz` };
  }
  return { ...menor, cabeNaGpu: false,
    motivo: `nenhum cabe em ${(orcamento / GiB).toFixed(1)} GiB; vai rodar parte na CPU (lento, mas responde)` };
}

/**
 * Solta um modelo da memória agora.
 *
 * `keep_alive: 0` é a forma suportada de descarregar: o Ollama não tem rota de
 * "unload", ele expira por tempo. Zerar o tempo faz expirar imediatamente.
 */
export async function descarrega(nome) {
  try {
    const r = await pede("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: nome, keep_alive: 0 }),
    }, 15000);
    return r.ok;
  } catch {
    return false;
  }
}

/**
 * Libera a GPU inteira pra voz. É a função que dá nome ao módulo.
 *
 * Chamada ANTES de subir Chatterbox/Whisper. Devolve o que soltou pra quem
 * chamou poder dizer o que fez — soltar em silêncio deixaria a pessoa achando
 * que o modelo sumiu sozinho.
 *
 * TRÊS RESULTADOS DIFERENTES, e é por isso que não devolve só uma lista:
 *
 *   ok:true  + soltos:[]      nada estava carregado; a GPU já estava livre
 *   ok:true  + soltos:[...]   liberou o que estava lá
 *   ok:false                  NÃO SEI se está livre — ou não deu pra consultar,
 *                             ou algum modelo recusou sair
 *
 * O terceiro caso é o que importa. Quem chama precisa poder subir a voz mesmo
 * assim (talvez caiba), mas dizendo que subiu sem garantia — em vez de afirmar
 * uma folga que não conferiu.
 *
 * Não aborta no primeiro erro: liberar 2 de 3 já pode bastar pra voz caber, e
 * parar no primeiro desperdiçaria isso.
 */
export async function cedeGpu() {
  let presos;
  try {
    presos = await residentes();
  } catch (e) {
    return { ok: false, soltos: [], resistiram: [],
      motivo: `não deu pra saber o que estava carregado: ${String(e.message).slice(0, 80)}` };
  }

  const soltos = [];
  const resistiram = [];
  for (const m of presos) {
    if (await descarrega(m.nome)) soltos.push(m.nome);
    else resistiram.push(m.nome);
  }

  if (resistiram.length) {
    return { ok: false, soltos, resistiram,
      motivo: `não saíram da memória: ${resistiram.join(", ")}` };
  }
  return { ok: true, soltos, resistiram: [],
    motivo: soltos.length ? `liberei ${soltos.join(", ")}` : "a GPU já estava livre" };
}

/**
 * Carrega um modelo na memória sem gerar texto, pra primeira pergunta real não
 * pagar os ~13 s de carregamento a frio (a quente são ~300 ms nesta máquina).
 *
 * Best-effort de propósito: aquecer é otimização, e otimização que derruba o
 * chamador é defeito.
 */
export async function aquece(nome, keepAlive = "5m") {
  try {
    const r = await pede("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: nome, keep_alive: keepAlive }),
    }, 120000);
    return r.ok;
  } catch {
    return false;
  }
}

/** Retrato pro `doctor` e pro painel: o que dá pra usar e a que custo. */
export async function resumo() {
  const est = await disponivel();
  if (!est.ok) return { ok: false, motivo: est.motivo, modelos: [], residentes: [] };
  const [lista, presos, livre, escolhido] = await Promise.all([
    modelos(),
    /* `null` aqui é "não deu pra consultar", diferente de `[]` = "nada
       carregado". O doctor imprime os dois de formas diferentes, senão uma
       consulta quebrada viraria "tudo tranquilo" na tela. */
    residentes().catch(() => null),
    vramLivreBytes(),
    escolhe(),
  ]);
  return {
    ok: true,
    base: base(),
    modelos: lista,
    residentes: presos,
    vramLivreGiB: livre === null ? null : Number((livre / GiB).toFixed(2)),
    escolhido,
  };
}
