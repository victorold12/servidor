/**
 * Instalar os motores de voz DENTRO do app, sem terminal e sem arquivo em
 * Documentos. É o outro lado do botão "Instalar tudo" da aba Voz.
 *
 * ---------------------------------------------------------------------------
 * POR QUE O .bat CONTINUA EXISTINDO POR BAIXO
 *
 * A tentação óbvia era reescrever a instalação em JavaScript aqui e apagar o
 * .bat. Não: o .bat é a ÚNICA parte deste projeto que já foi executada num
 * Windows real, de ponta a ponta, por um workflow (testa-instalador.yml). Cada
 * linha dele corresponde a um erro que custou uma madrugada — o PATH que não
 * recarrega depois do winget, o torch que não tem instalador pro Python novo, a
 * marca-d'água do perth que mata o servidor 4 GB depois de baixar o modelo.
 * Reescrever isso em Node significaria jogar fora a única prova que existe e
 * recomeçar a cobrar o mesmo preço.
 *
 * Então este módulo NÃO instala nada por conta própria. Ele roda o mesmo .bat,
 * lê a saída linha a linha e devolve pro painel. O que muda pro usuário é onde
 * o texto aparece — dentro do JARVIS, não numa janela preta.
 *
 * ---------------------------------------------------------------------------
 * POR QUE O SCRIPT NÃO VEM DO RENDERER
 *
 * O caminho mais curto seria o painel gerar o .bat (ele já sabe: é o mesmo
 * código do botão de download) e mandar o TEXTO por IPC pra cá executar. Isso
 * abriria um cano de execução de código arbitrário no PC, atravessando o gate
 * de 4 camadas inteiro (docs/SEGURANCA-AGENTE-LOCAL.md) — e o renderer é
 * justamente a janela que transforma resposta de modelo em HTML. Um XSS ali, ou
 * um modelo convencendo o painel a montar outra string, e o "instalador" instala
 * outra coisa.
 *
 * Então o .bat é ASSADO em tempo de build (scripts/prepare-webapp.js roda o
 * gerador do painel, o mesmo que o CI testa) e vive em webapp/instaladores/. O
 * renderer manda por IPC apenas um id de modelo do whisper, conferido contra a
 * lista fechada abaixo. O pior que um renderer comprometido consegue é escolher
 * entre cinco arquivos que já estavam no disco.
 * ---------------------------------------------------------------------------
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** Lista fechada. O que não está aqui não roda — ver o cabeçalho. */
export const MODELOS_WHISPER = ["tiny", "base", "small", "medium", "large-v3"];

export const nomeDoInstalador = (modelo) => `instalar-tudo-${modelo}.bat`;

/** Pasta onde o prepare-webapp assou os .bat, dentro de webapp/. */
export const PASTA_INSTALADORES = "instaladores";

/**
 * Resolve o .bat de um modelo. Falha alto e claro nos dois casos que importam:
 * modelo fora da lista (tentativa de escapar) e arquivo ausente (build feito
 * sem o prepare-webapp novo — o app estaria prometendo um botão que não anda).
 */
export function caminhoDoInstalador(webappDir, modelo) {
  if (!MODELOS_WHISPER.includes(modelo)) {
    throw new Error(`Modelo de whisper desconhecido: ${JSON.stringify(String(modelo)).slice(0, 60)}`);
  }
  const alvo = path.join(webappDir, PASTA_INSTALADORES, nomeDoInstalador(modelo));
  if (!fs.existsSync(alvo)) {
    throw new Error(
      `Falta ${alvo}. Este build foi empacotado sem os instaladores — ` +
        `rode "npm run prepare-webapp" no electron-shell e refaça o pacote.`
    );
  }
  return alvo;
}

/**
 * Onde o .bat instala tudo. Tem que ser o MESMO lugar que ele calcula sozinho,
 * senão o app procuraria os motores num canto e eles estariam noutro.
 *
 * O .bat pergunta ao registro (HKCU\...\Shell Folders /v Personal) porque em
 * Windows em português a pasta APARECE como "Documentos" e no disco costuma se
 * chamar "Documents" — e pode ter sido movida pro OneDrive. `app.getPath` do
 * Electron consulta a mesma known folder, então os dois chegam no mesmo lugar
 * nos três casos. Por isso `documentos` vem de fora, do main.
 */
export const raizDasVozes = (documentos) => path.join(documentos, "VTz LLM");

/**
 * Como ligar cada motor, olhando o que REALMENTE está no disco.
 *
 * Roda o python do venv direto, sem `activate.bat` e sem `cmd /k`. O
 * ligar-vozes.bat que o instalador deixa na pasta abre duas janelas de terminal
 * — de propósito, porque lá elas são o único lugar onde o erro apareceria. Aqui
 * o log vai pro painel, então janela preta seria só a coisa que este item veio
 * eliminar. Ativar um venv não faz mágica nenhuma: é PATH. Chamar o
 * .venv\Scripts\python.exe dá exatamente o mesmo interpretador.
 *
 * O ponto de entrada é DETECTADO, não chutado. O Chatterbox tem server.py; o
 * Kokoro nunca foi ligado por ninguém neste projeto (docs/PROXIMA-FASE.md diz
 * "não testado ainda", com `python -m uvicorn api.src.main:app` como palpite).
 * Chutar um comando fixo faria o motor não subir e o log dizer "arquivo não
 * encontrado", que não ajuda ninguém a consertar. Procurar os dois formatos e
 * dizer qual foi achado (ou que nenhum foi) é honesto e conserta sozinho quando
 * o palpite estiver certo.
 */
export function comoLigar(pasta, porta) {
  const python = process.platform === "win32"
    ? path.join(pasta, ".venv", "Scripts", "python.exe")
    : path.join(pasta, ".venv", "bin", "python");
  if (!fs.existsSync(python)) return { instalado: false, motivo: "ambiente virtual não encontrado" };

  if (fs.existsSync(path.join(pasta, "server.py"))) {
    return { instalado: true, python, args: ["server.py"], via: "server.py" };
  }
  if (fs.existsSync(path.join(pasta, "api", "src", "main.py"))) {
    /* Ter o venv NÃO é ter as dependências. Aconteceu de verdade com o Kokoro: o
       instalador recusava instalar (o projeto usa pyproject.toml, e o script só
       sabia ler requirements.txt), então o `.venv` ficava criado e vazio. Aqui
       isso virava "instalado: true", o app tentava subir, e o log dizia
       "No module named uvicorn" — que parece defeito do Kokoro, não instalação
       que nunca aconteceu.

       Conferir o executável do uvicorn é barato (é só um `existsSync`) e
       responde a pergunta certa: dá pra rodar ISTO agora? */
    const uvicorn = process.platform === "win32"
      ? path.join(pasta, ".venv", "Scripts", "uvicorn.exe")
      : path.join(pasta, ".venv", "bin", "uvicorn");
    if (!fs.existsSync(uvicorn)) {
      return { instalado: false, motivo: "o ambiente existe mas está vazio (falta o uvicorn) — a instalação não chegou a terminar" };
    }
    return {
      instalado: true,
      python,
      args: ["-m", "uvicorn", "api.src.main:app", "--host", "127.0.0.1", "--port", String(porta)],
      via: "uvicorn api.src.main:app",
    };
  }
  return { instalado: false, motivo: "não achei server.py nem api/src/main.py na pasta" };
}

/** Os dois motores, já resolvidos contra o disco. */
export function motoresEmDisco(documentos) {
  const vozes = path.join(raizDasVozes(documentos), "vozes");
  return [
    { id: "chatterbox", nome: "Chatterbox", porta: 8004, pasta: path.join(vozes, "Chatterbox-TTS-Server") },
    { id: "kokoro", nome: "Kokoro", porta: 8880, pasta: path.join(vozes, "Kokoro-FastAPI") },
  ].map((m) => ({ ...m, ...comoLigar(m.pasta, m.porta) }));
}

/**
 * Quebra um fluxo em linhas. Um `data` do pipe não vem alinhado com \n — cai no
 * meio de uma linha — então emitir o pedaço cru mostraria o log picado ao meio.
 * O resto fica guardado até a próxima parte chegar.
 */
function porLinha(fluxo, aoLinha) {
  let resto = "";
  fluxo.setEncoding("utf8");
  fluxo.on("data", (parte) => {
    const linhas = (resto + parte).split(/\r?\n/);
    resto = linhas.pop();
    for (const l of linhas) aoLinha(l);
  });
  fluxo.on("end", () => {
    if (resto) aoLinha(resto);
    resto = "";
  });
}

/**
 * Mata o processo e TUDO que ele criou. `filho.kill()` sozinho não serve no
 * Windows: derruba o cmd.exe e deixa o pip, o git e o download de 2 GB rodando
 * órfãos — cancelar não cancelaria nada, só tiraria o log da tela. /T pega a
 * árvore, /F não pede licença.
 */
function mataArvore(filho) {
  if (!filho || filho.exitCode !== null || filho.signalCode !== null) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(filho.pid), "/T", "/F"], { windowsHide: true });
  } else {
    filho.kill("SIGTERM");
  }
}

/**
 * Roda o .bat e devolve cada linha por `aoLinha`.
 *
 * JARVIS_SEM_PAUSA: o script chama `pause` em vários pontos, esperando alguém
 * apertar tecla. Sem ninguém na frente de um terminal — que é exatamente o caso
 * aqui — ele ficaria parado pra sempre e o painel mostraria uma barra que nunca
 * anda. A variável já existe e é como o CI do Windows executa isto.
 *
 * O .bat é COPIADO pra uma pasta temporária antes de rodar. Em produção ele mora
 * dentro de resources\webapp, sob Arquivos de Programas, e um script rodando de
 * lá esbarra em permissão de escrita e em antivírus que olham torto pra .bat
 * executado de dentro de pasta de programa. A cópia custa 25 KB.
 */
export function rodaInstalador({ bat, pastaTemp, aoLinha }) {
  const copia = path.join(
    fs.mkdtempSync(path.join(pastaTemp || os.tmpdir(), "jarvis-vozes-")),
    path.basename(bat)
  );
  fs.copyFileSync(bat, copia);

  /* Sem `shell: true`: programa e argumentos vão separados, que é a regra do
     projeto inteiro (docs/SEGURANCA-AGENTE-LOCAL.md). O cmd.exe aqui não é um
     shell interpretando string do usuário — é o interpretador do .bat, e o
     caminho vem de mkdtemp, não de ninguém de fora. */
  const filho = spawn(process.env.ComSpec || "cmd.exe", ["/d", "/c", copia], {
    cwd: path.dirname(copia),
    windowsHide: true,
    env: { ...process.env, JARVIS_SEM_PAUSA: "1" },
  });

  porLinha(filho.stdout, aoLinha);
  porLinha(filho.stderr, aoLinha);

  const terminou = new Promise((resolve) => {
    filho.on("error", (err) => resolve({ ok: false, erro: err.message }));
    filho.on("close", (codigo) => {
      /* Apaga a cópia; se não der, paciência — é o %TEMP%, o Windows limpa. */
      fs.rm(path.dirname(copia), { recursive: true, force: true }, () => {});
      resolve({ ok: codigo === 0, codigo });
    });
  });

  return { filho, terminou, cancela: () => mataArvore(filho) };
}

/**
 * Alguém já está atendendo nesta porta? Só isso — abre, fecha, responde.
 * Não é health check: não pergunta SE é o Chatterbox, porque pra decidir "subo
 * ou não subo" a única coisa que importa é se a porta está ocupada.
 */
export function portaRespondendo(porta, timeout = 400) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    const fim = (r) => { s.destroy(); resolve(r); };
    s.setTimeout(timeout);
    s.once("connect", () => fim(true));
    s.once("timeout", () => fim(false));
    s.once("error", () => fim(false));
    s.connect(porta, "127.0.0.1");
  });
}

/**
 * Sobe os motores instalados. Devolve os filhos pra quem chamou poder derrubar
 * quando o app sair.
 *
 * O stdout dos servidores É LIDO, não ignorado. Não é pelo log: é porque um pipe
 * que ninguém lê enche (64 KB no Windows) e o processo TRAVA na próxima escrita.
 * O Chatterbox imprime o progresso de um download de 2 GB — ele encheria o pipe
 * e congelaria parecendo que subiu e ficou mudo.
 */
/**
 * Acha o gerente de residência do modelo local, que vive no agente-local.
 *
 * Dois lugares porque são duas realidades: empacotado, o agente vai pra
 * `resources/`; em desenvolvimento (e no CI), fica ao lado do electron-shell.
 *
 * `fileURLToPath`/`pathToFileURL` e não manipulação de string: no Windows,
 * `new URL(import.meta.url).pathname` devolve `/C:/Users/VTz%20produti/...` —
 * com barra sobrando e espaço escapado. Já quebrou dois scripts deste projeto.
 */
async function gerenteDaGpu() {
  const aqui = path.dirname(fileURLToPath(import.meta.url));
  const candidatos = [
    process.resourcesPath && path.join(process.resourcesPath, "agente-local", "src", "ollama.js"),
    path.resolve(aqui, "..", "..", "agente-local", "src", "ollama.js"),
  ].filter(Boolean);
  for (const c of candidatos) {
    if (fs.existsSync(c)) {
      try {
        return await import(pathToFileURL(c).href);
      } catch { /* módulo quebrado é o mesmo que ausente pra este propósito */ }
    }
  }
  return null;
}

/**
 * Devolve a VRAM antes de subir a voz.
 *
 * POR QUE ISTO PRECISA ACONTECER AQUI
 *
 * A GPU desta classe de máquina tem 8 GiB e o desktop já come metade. Se o
 * modelo de linguagem estiver residente, o Chatterbox carrega no que sobrou —
 * e quando não sobra, ele NÃO reclama: sobe, atende na 8004 e não fala. É a
 * falha mais cara já paga neste projeto, e ela é silenciosa.
 *
 * A assimetria decide quem cede: o modelo perdendo a GPU cai na nuvem por meio
 * centavo; a voz perdendo emudece sem avisar. Então o modelo cede, sempre.
 *
 * Nunca impede a voz de subir. Mesmo sem conseguir liberar, talvez caiba — o
 * que não pode é subir ACHANDO que tem folga. Por isso o caso "não sei" vira
 * aviso explícito no log em vez de silêncio.
 */
async function liberaGpuParaVoz(aoLinha) {
  const mod = await gerenteDaGpu();
  if (!mod) {
    aoLinha("[GPU] gerente do modelo local não encontrado — subindo a voz sem liberar VRAM.");
    return;
  }
  const est = await mod.disponivel();
  if (!est.ok) {
    /* Sem Ollama no ar não há modelo nosso segurando VRAM. Estado normal na
       maioria das máquinas, e por isso não é aviso: é informação. */
    aoLinha("[GPU] nenhum modelo local no ar; a VRAM já está com a voz.");
    return;
  }
  const r = await mod.cedeGpu();
  if (r.ok) {
    aoLinha(`[GPU] ${r.motivo}.`);
  } else {
    aoLinha(`[GPU] ATENÇÃO: ${r.motivo}. A voz vai subir mesmo assim, mas pode não ter VRAM — `
      + "se ela atender na porta e não falar, foi isto.");
  }
}

export async function ligaMotores({ documentos, aoLinha }) {
  const vivos = [];
  /* Antes de qualquer spawn: a voz tem prioridade sobre o modelo na GPU. */
  await liberaGpuParaVoz(aoLinha);
  for (const m of motoresEmDisco(documentos)) {
    if (!m.instalado) {
      aoLinha(`[${m.nome}] não subiu: ${m.motivo}`);
      continue;
    }
    /* O instalador deixa um atalho na Inicialização do Windows que roda o
       ligar-vozes.bat no login. Quem instalou ontem já tem os dois servidores de
       pé quando abre o JARVIS hoje — subir de novo daria "address already in
       use", e o segundo processo morreria deixando no log um erro que parece
       falha de instalação. Perguntar à porta custa milissegundos e some com
       essa classe inteira de confusão. */
    if (await portaRespondendo(m.porta)) {
      aoLinha(`[${m.nome}] já estava no ar na porta ${m.porta} — deixando como está.`);
      continue;
    }
    const filho = spawn(m.python, m.args, { cwd: m.pasta, windowsHide: true });
    porLinha(filho.stdout, (l) => aoLinha(`[${m.nome}] ${l}`));
    porLinha(filho.stderr, (l) => aoLinha(`[${m.nome}] ${l}`));
    filho.on("error", (err) => aoLinha(`[${m.nome}] não subiu: ${err.message}`));
    filho.on("close", (c) => aoLinha(`[${m.nome}] o servidor encerrou (código ${c}).`));
    aoLinha(`[${m.nome}] subindo na porta ${m.porta} (${m.via}).`);
    vivos.push({ id: m.id, nome: m.nome, porta: m.porta, filho });
  }
  return vivos;
}

export function paraMotores(vivos) {
  for (const v of vivos || []) mataArvore(v.filho);
}
