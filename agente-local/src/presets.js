/**
 * Perfis de instalação — instalar em camadas, não tudo ou nada.
 *
 * ---------------------------------------------------------------------------
 * O PROBLEMA
 *
 * Hoje a instalação é "Instalar TUDO neste PC": Chatterbox, Kokoro, whisper,
 * ffmpeg, torch. São vários GB, dezenas de minutos, e um venv de Python que já
 * quebrou de cinco jeitos diferentes documentados no CLAUDE.md.
 *
 * Quem só quer conversar por texto paga esse preço inteiro pra não usar nada
 * dele. E quando algo falha no meio, falha um monte de coisa junto — o que
 * torna o diagnóstico mais difícil exatamente quando ele mais importa.
 *
 * ---------------------------------------------------------------------------
 * A IDEIA: CAMADAS QUE DEPENDEM UMA DA OUTRA
 *
 * Cada perfil é um conjunto de capacidades, e capacidade é o que o
 * `capacidades.js` já sabe verificar EXERCITANDO o caminho. Nada aqui inventa
 * verificação nova: este arquivo diz o que É PRECISO, e o outro diz o que
 * FUNCIONA. Separar as duas perguntas é o que evita um instalador que se
 * declara satisfeito sozinho.
 *
 * ---------------------------------------------------------------------------
 * POR QUE O PADRÃO É O MENOR
 *
 * O perfil `texto` sobe em segundos e não instala Python nenhum. Quem quiser
 * voz escolhe, e escolhendo entende o que está pedindo — em vez de descobrir
 * pelo tempo de instalação.
 *
 * Isso também muda o suporte: "instalei o perfil texto e o chat não abre" é uma
 * pergunta respondível. "instalei tudo e algo falhou" não é.
 */

/**
 * Ordem importa: cada perfil inclui os anteriores. Uma camada que dependesse
 * de outra sem dizer produziria o pior tipo de falha — a que aparece longe da
 * causa, que é o padrão de defeito mais caro deste projeto.
 */
export const PERFIS = {
  texto: {
    titulo: "Só texto",
    descricao: "Conversa, documentos e agentes. Não instala Python nem baixa modelo.",
    tempo: "segundos",
    capacidades: ["cofre", "backend"],
  },
  escuta: {
    titulo: "Texto + escuta",
    descricao: 'Acrescenta ditado e "Ei, JARVIS". Baixa o whisper e o ffmpeg (~200 MB).',
    tempo: "poucos minutos",
    inclui: "texto",
    capacidades: ["ffmpeg", "whisper"],
  },
  voz: {
    titulo: "Completo com voz",
    descricao: "Acrescenta o JARVIS falando com voz clonada. Precisa de Python 3.12 "
             + "e baixa vários GB (torch).",
    tempo: "dezenas de minutos",
    inclui: "escuta",
    capacidades: ["chatterbox"],
  },
  local: {
    titulo: "Completo + modelo local",
    descricao: "Acrescenta responder sem gastar crédito, com o modelo rodando aqui.",
    tempo: "mais alguns minutos",
    inclui: "voz",
    capacidades: ["ollama"],
  },
};

export const PADRAO = "texto";

/** Todas as capacidades de um perfil, seguindo a cadeia de `inclui`. */
export function capacidadesDe(perfil) {
  const vistos = new Set();
  const saida = [];
  let atual = perfil;
  while (atual) {
    const p = PERFIS[atual];
    if (!p) throw new Error(`perfil desconhecido: ${atual}`);
    /* Do mais básico pro mais avançado: `unshift` porque a cadeia é percorrida
       de trás pra frente, e a ordem de instalação importa. */
    for (const c of [...p.capacidades].reverse()) {
      if (!vistos.has(c)) { vistos.add(c); saida.unshift(c); }
    }
    atual = p.inclui;
  }
  return saida;
}

/**
 * O que falta pra este PC atender ao perfil.
 *
 * `verifica` é injetado (o `capacidades.js` no uso real) porque exercitar cada
 * capacidade custa segundos e chama binário — o teste precisa poder responder
 * sem isso, e o app precisa poder verificar só o subconjunto do perfil em vez
 * de tudo.
 */
export async function diagnostica(perfil, verifica) {
  const necessarias = capacidadesDe(perfil);
  const linhas = await verifica(necessarias);
  const faltando = linhas.filter((l) => !l.ok && !l.opcional);
  return {
    perfil,
    titulo: PERFIS[perfil].titulo,
    completo: faltando.length === 0,
    necessarias,
    faltando,
    /* O primeiro que falta é o que resolver primeiro: as camadas dependem umas
       das outras, e mandar consertar a última seria mandar consertar o sintoma. */
    proximoPasso: faltando[0]?.resolver || "",
  };
}

/**
 * Qual o maior perfil que este PC já atende?
 *
 * Serve pra o app dizer "você está no perfil escuta" sem perguntar nada — e
 * principalmente pra não oferecer instalar o que já está instalado, que é como
 * um instalador reinstala torch sem necessidade e quebra o que funcionava.
 */
export async function perfilAtual(verifica) {
  const ordem = ["local", "voz", "escuta", "texto"];
  for (const p of ordem) {
    const d = await diagnostica(p, verifica);
    if (d.completo) return p;
  }
  return null;      // nem o mínimo: null é diferente de "texto"
}

/** Lista pronta pra tela de escolha. */
export function paraEscolha() {
  return Object.entries(PERFIS).map(([id, p]) => ({
    id, titulo: p.titulo, descricao: p.descricao, tempo: p.tempo,
    padrao: id === PADRAO,
    capacidades: capacidadesDe(id),
  }));
}
