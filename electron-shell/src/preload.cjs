/**
 * Preload da janela principal. CommonJS de propósito — preload sandboxed do
 * Electron precisa disso independente do "type":"module" do package.json.
 *
 * Capability allowlist explícita e nomeada (Seção 13.1 do esquema — padrão
 * absorvido do Tauri): a Web App só enxerga exatamente o que é exposto aqui,
 * nada de nodeIntegration nem acesso livre a módulos do Node. Hoje só expõe
 * um sinalizador — é o ponto de extensão pronto pra quando a Web App quiser
 * se adaptar ao rodar dentro do shell (ex.: esconder algo que só faz sentido
 * no navegador). Adicionar uma capability = adicionar uma linha aqui, nomeada.
 */
const { contextBridge, ipcRenderer } = require("electron");

// URL do backend pareado, injetada pelo main.js via webPreferences.
// additionalArguments (process.argv funciona mesmo no preload sandboxed).
// Sem isto, o painel web dentro do Electron não sabia qual backend usar — só
// tentava localhost:8000 — e a aba "Agente Local" ficava vazia mesmo com o
// agente pareado e conectado (bug real, achado testando o .msi no Windows).
function argValue(prefix) {
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : null;
}

// `process` aqui é o global do Node exposto pelo próprio preload (mesmo sob
// sandbox) — não precisa (e não dá pra) importar do pacote "electron".
contextBridge.exposeInMainWorld("jarvisDesktop", {
  isElectron: true,
  platform: process.platform,
  backendUrl: argValue("--jarvis-backend-url="),

  /* Notificação nativa do Windows. A Notification API do navegador dentro do
   * Electron pede permissão e não acende o ícone da barra de tarefas; quem faz
   * isso direito é o processo principal. Só título e corpo cruzam a ponte —
   * nada de callback nem HTML, pra a superfície continuar do tamanho do que
   * a capability precisa. */
  notify(titulo, corpo) {
    ipcRenderer.send("jarvis:notify", { titulo: String(titulo || ""), corpo: String(corpo || "") });
  },

  /* Instalação dos motores de voz sem sair do app (ver src/instalador-vozes.js).
   *
   * A superfície é do tamanho do que a tela precisa e nem um grão a mais. Em
   * particular NÃO existe "rode este script": `instalar` recebe só o nome de um
   * modelo do whisper, e quem decide o que roda é o processo principal, a partir
   * de arquivos que já estavam no disco desde o build. Se esta ponte aceitasse
   * texto de script, um XSS no painel — que renderiza resposta de modelo como
   * HTML — viraria execução de código no PC, atravessando o gate de 4 camadas
   * inteiro.
   *
   * `String(modelo)` aqui não é validação (a de verdade é a lista fechada no
   * main); é só pra não mandar um objeto pelo canal e o erro aparecer do outro
   * lado, longe de onde foi causado. */
  vozes: {
    estado: () => ipcRenderer.invoke("jarvis:vozes-estado"),
    instalar: (modelo) => ipcRenderer.invoke("jarvis:vozes-instalar", String(modelo || "")),
    ligar: () => ipcRenderer.invoke("jarvis:vozes-ligar"),
    cancelar: () => ipcRenderer.invoke("jarvis:vozes-cancelar"),

    /* O `event` do Electron NÃO atravessa: ele carrega `sender`, e entregar isso
     * ao renderer devolveria de bandeja o acesso a IPC arbitrário que o
     * contextBridge existe pra impedir. Só o payload passa.
     *
     * Devolve a função de cancelar a inscrição: sem ela, abrir a aba Voz dez
     * vezes deixaria dez ouvintes vivos, e cada linha de log seria escrita dez
     * vezes na tela. */
    aoProgredir(cb) {
      const ouvinte = (_evt, dados) => cb(dados);
      ipcRenderer.on("jarvis:vozes-progresso", ouvinte);
      return () => ipcRenderer.removeListener("jarvis:vozes-progresso", ouvinte);
    },
  },
});
