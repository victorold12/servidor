/**
 * Prepara texto para ser FALADO, não lido.
 *
 * ---------------------------------------------------------------------------
 * O PROBLEMA
 *
 * A resposta do modelo é markdown com emoji: `**Pronto!** 🎉 Instalei 3 apps
 * (100% ok) — veja em https://exemplo.com/x?y=1`. Isso vai inteiro pro motor de
 * TTS, que não sabe que aquilo é formatação. O resultado é o JARVIS soletrando
 * "asterisco asterisco", lendo "hash" antes de cada título, e recitando uma URL
 * caractere a caractere.
 *
 * Um humano lendo esse mesmo texto em voz alta não fala nada disso: ele fala o
 * conteúdo e usa a formatação como PISTA de entonação. É isso que este módulo
 * imita.
 *
 * ---------------------------------------------------------------------------
 * DUAS REGRAS QUE GUIARAM AS ESCOLHAS
 *
 * 1. Na dúvida, CORTAR em vez de tentar ler. Emoji, URL e bloco de código não
 *    têm boa forma falada — inventar uma ("carinha piscando") é pior que o
 *    silêncio, porque atrapalha quem está ouvindo o resto.
 *
 * 2. Marcador de estrutura vira PAUSA, não palavra. Item de lista não é "traço
 *    item"; é uma frase curta com ponto no fim. A pontuação é o único controle
 *    de ritmo que o TTS entende, então ela é onde a formatação tem que
 *    aterrissar.
 *
 * Isto NÃO é tradutor de tudo: números, siglas e datas ficam como estão. O
 * Chatterbox e o Kokoro já leem número em português; reescrever aqui só criaria
 * um segundo lugar pra errar.
 */

/* Blocos Unicode de emoji e pictogramas, mais os modificadores que os
   acompanham (seletor de variação, tom de pele, e o juntador de largura zero
   que forma emojis compostos como 👨‍👩‍👧). Sem varrer os modificadores junto,
   sobram caracteres invisíveis que alguns motores leem como ruído. */
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE00}-\u{FE0F}\u{1F3FB}-\u{1F3FF}\u{200D}\u{20E3}\u{2190}-\u{21FF}\u{2300}-\u{23FF}]/gu;

/** Símbolos que têm leitura em português e por isso valem a troca. */
const SIMBOLOS = [
  [/(\d)\s*%/g, "$1 por cento"],
  [/R\$\s*([\d.,]+)/g, "$1 reais"],
  [/US\$\s*([\d.,]+)/g, "$1 dólares"],
  [/(\d)\s*°C/g, "$1 graus"],
  [/\s*(->|→|=>)\s*/g, " para "],
  [/\s+&\s+/g, " e "],
  [/\s*\+\s*/g, " mais "],
];

/**
 * Devolve o texto pronto pra falar.
 *
 * A ordem importa: blocos de código saem ANTES de qualquer outra coisa, senão
 * o que está dentro deles (que costuma ser cheio de símbolo) passa pelas
 * outras regras e vira uma frase sem sentido.
 */
export function paraFala(entrada) {
  let t = String(entrada ?? "");

  /* Bloco de código: some inteiro. Ler `const x = {a: 1}` em voz alta não
     ajuda ninguém — quem quer o código está olhando a tela, e quem está
     ouvindo perdeu o fio da conversa. */
  t = t.replace(/```[\s\S]*?```/g, " ");
  t = t.replace(/~~~[\s\S]*?~~~/g, " ");

  /* Imagem antes de link: a sintaxe da imagem CONTÉM a do link, e na ordem
     inversa sobraria um "!" solto onde a imagem estava. */
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
  t = t.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");   // link: fica só o texto

  /* URL solta. Nenhuma leitura de "h t t p s dois pontos barra barra" é boa;
     dizer que existe um link e seguir é o que um humano faria. */
  /* Sem parênteses: o motor faz uma pausa em cada um, e "abre parêntese link
     fecha parêntese" é justamente o tipo de leitura de pontuação que este
     arquivo existe pra eliminar. */
  t = t.replace(/\bhttps?:\/\/\S+/gi, " um link ");
  t = t.replace(/\b[\w.-]+@[\w.-]+\.\w+\b/g, " um email ");

  /* Caminho de arquivo: ler "C dois pontos barra usuários barra" é o pior caso
     de todos. Fica só o nome do arquivo, que é a parte que a pessoa reconhece.

     Duas formas, e a ordem importa. A primeira aceita ESPAÇO no meio e para na
     extensão — sem isso, "C:\Users\VTz produti\..." era cortado no espaço do
     nome da pasta e sobrava "VTz produti\Documents\prova-voz.wav" pra ser
     soletrado. A segunda pega pasta sem extensão, aí sem espaço, porque num
     texto corrido não há como distinguir "a pasta C:\dados e o resto" de um
     nome de pasta que contenha " e o resto". */
  t = t.replace(/[A-Za-z]:\\[^\n]*?\.[A-Za-z0-9]{1,5}\b/g, (m) => " " + m.split("\\").pop() + " ");
  t = t.replace(/[A-Za-z]:\\[^\s,;"']*/g, (m) => " " + (m.split("\\").filter(Boolean).pop() || "") + " ");

  t = t.replace(/`([^`]+)`/g, "$1");               // código curto: só o conteúdo

  /* Marcadores de estrutura viram PAUSA. Cada item de lista fecha com ponto
     pra o motor respirar entre eles — sem isso a lista sai como uma frase só,
     ofegante. */
  /* O ponto só entra se o texto já não terminar em pontuação — senão um título
     como "## Pronto!" virava "Pronto!." e o motor lê o ponto extra como uma
     pausa engasgada. Vale pros dois tipos de item de lista também. */
  const fecha = (s) => (/[.!?:;,]$/.test(s.trim()) ? s.trim() : s.trim() + ".");
  t = t.replace(/^\s{0,3}#{1,6}\s+(.+)$/gm, (_, x) => fecha(x));   // título
  t = t.replace(/^\s*>\s?/gm, "");                          // citação
  t = t.replace(/^\s*[-*+]\s+(.+)$/gm, (_, x) => fecha(x));       // item de lista
  t = t.replace(/^\s*\d+[.)]\s+(.+)$/gm, (_, x) => fecha(x));     // item numerado
  t = t.replace(/^\s*([-*_]\s*){3,}\s*$/gm, " ");           // linha divisória

  /* Tabela: as barras viram vírgula, que é a pausa curta que separa colunas na
     fala. A linha de trace (|---|---|) não tem conteúdo e sai fora. */
  t = t.replace(/^\s*\|[\s:|-]+\|\s*$/gm, " ");
  t = t.replace(/\s*\|\s*/g, ", ");

  t = t.replace(/(\*\*\*|\*\*|\*|___|__|~~)/g, "");         // negrito, itálico, riscado
  t = t.replace(/(?<=\w)_(?=\w)/g, " ");                    // nome_com_underline

  t = t.replace(EMOJI, " ");

  for (const [re, por] of SIMBOLOS) t = t.replace(re, por);

  /* Pontuação repetida vira uma só. "..." e "!!!" fazem alguns motores
     alongarem a pausa de forma estranha, e "—" costuma sair soletrado. */
  t = t.replace(/[–—]/g, ", ");
  t = t.replace(/\.{2,}/g, ".");
  t = t.replace(/([!?]){2,}/g, "$1");
  t = t.replace(/["“”«»]/g, "");

  /* As quebras de linha viram ponto ANTES da faxina de pontuação, e não depois.
     Na ordem inversa a faxina rodava cedo demais: "prova-voz.wav  \nDetalhes"
     virava "prova-voz.wav . Detalhes", com o espaço solto antes do ponto que
     ninguém tinha mais chance de limpar. */
  t = t.replace(/[ \t]+/g, " ");
  t = t.replace(/\n{2,}/g, ". ");
  t = t.replace(/\n/g, ". ");

  /* Sobra de pontuação depois de tanto corte: ", ." ou ". ." não existem em
     fala e o motor tropeça neles. */
  t = t.replace(/\s+([,.;:!?])/g, "$1");
  t = t.replace(/([,.;:])\1+/g, "$1");
  /* ":", ";" e "," seguidos de ponto: acontece quando a linha já terminava com
     eles e a quebra de linha virou ponto ("... (100% ok):" -> "ok):."). Duas
     pontuações seguidas fazem o motor dar duas pausas coladas. */
  t = t.replace(/[,;:]\s*\./g, ".");
  t = t.replace(/\.\s*,/g, ".");
  t = t.replace(/([!?])\s*\./g, "$1");
  t = t.replace(/\.\s*\./g, ".");
  t = t.replace(/\s+/g, " ").trim();

  /* Sem letra nem número, não há o que falar. Isto existe porque a conversão de
     linha em branco pra ponto acontece ANTES de sabermos se sobrou conteúdo: um
     texto só de espaços virava ".", e mandar um ponto sozinho pro motor produz
     um ruído curto que parece defeito. */
  if (!/[\p{L}\p{N}]/u.test(t)) return "";

  /* Termina com pontuação: sem isso o motor corta a última sílaba, porque não
     sabe que a frase acabou. */
  if (!/[.!?]$/.test(t)) t += ".";
  return t;
}
