/**
 * Processo principal da variante "JARVIS Agente Local" (Seção 10 do prompt
 * mestre): SEM janela da Web App — só bandeja + pareamento + a conexão do
 * Agente Local. Pra quem já usa o JARVIS pelo navegador (site) e só quer
 * habilitar controle do PC, sem abrir um segundo app com o painel duplicado.
 *
 * Reaproveita EXATAMENTE a mesma lógica de pareamento/conexão de main.js —
 * só remove a BrowserWindow do painel. Ver main.js pra a variante completa.
 */
import { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, dialog, shell } from "electron";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHELL_ROOT = path.resolve(__dirname, "..");
const ICON_PNG = path.join(SHELL_ROOT, "build", "icon.png");
const TRAY_PNG = path.join(SHELL_ROOT, "build", "tray.png");

function agenteLocalRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "agente-local")
    : path.resolve(SHELL_ROOT, "..", "agente-local");
}

function agenteLocalModule(...segments) {
  return pathToFileURL(path.join(agenteLocalRoot(), "src", ...segments)).href;
}

let tray = null;
let splash = null;
let wsConnection = null;
let lastStatusLabel = "iniciando…";
let auditPath = null; // resolvido via config.js (auditLogPath()) — não é caminho fixo daqui

function createSplash() {
  splash = new BrowserWindow({
    width: 380,
    height: 240,
    frame: false,
    resizable: false,
    movable: false,
    alwaysOnTop: true,
    backgroundColor: "#111114",
    icon: ICON_PNG,
    webPreferences: { contextIsolation: true },
  });
  splash.loadFile(path.join(__dirname, "splash.html"));
}

function closeSplash() {
  if (splash && !splash.isDestroyed()) splash.close();
  splash = null;
}

function rebuildTrayMenu() {
  if (!tray) return;
  const menu = Menu.buildFromTemplate([
    { label: `Status: ${lastStatusLabel}`, enabled: false },
    { type: "separator" },
    { label: "Ver auditoria local", enabled: !!auditPath, click: () => shell.showItemInFolder(auditPath) },
    { type: "separator" },
    { label: "Sair", click: () => app.quit() },
  ]);
  tray.setContextMenu(menu);
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(TRAY_PNG));
  tray.setToolTip("JARVIS Agente Local — iniciando…");
  rebuildTrayMenu();
}

/** Mesmo fluxo de main.js (pareamento estilo Smart TV, Seção 3) — comentários
 * completos lá; aqui só a chamada, sem duplicar a explicação. */
async function runPairingFlow() {
  const { loadConfig, saveConfig } = await import(agenteLocalModule("config.js"));
  const existing = loadConfig();
  if (existing) return existing;

  return new Promise((resolve, reject) => {
    const win = new BrowserWindow({
      width: 480,
      height: 440,
      resizable: false,
      icon: ICON_PNG,
      backgroundColor: "#111114",
      webPreferences: {
        preload: path.join(__dirname, "pairing-preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    win.setMenuBarVisibility(false);
    win.loadFile(path.join(__dirname, "pairing.html"));

    ipcMain.handle("pairing:start", async (_evt, { backendUrl, name, platform }) => {
      try {
        const { pairWithBackend } = await import(agenteLocalModule("pairing.js"));
        const { saveToken } = await import(agenteLocalModule("token-vault.js"));
        const result = await pairWithBackend({
          backendUrl,
          name,
          platform,
          onEvent: (evt) => { if (!win.isDestroyed()) win.webContents.send("pairing:event", evt); },
        });
        await saveToken(result.agentToken);
        const cfg = { agentId: result.agentId, backendUrl, name, platform, allowedRoots: result.allowedRoots || [] };
        saveConfig(cfg);
        resolve(cfg);
        win.close();
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err.message };
      }
    });

    win.on("closed", () => {
      ipcMain.removeHandler("pairing:start");
      reject(new Error("Pareamento cancelado."));
    });
  });
}

async function connectAgent(cfg) {
  const { getToken } = await import(agenteLocalModule("token-vault.js"));
  const { createAgentConnection } = await import(agenteLocalModule("ws-client.js"));
  const { createNativeConfirm } = await import(agenteLocalModule("confirm.js"));
  const { createCommandHandler } = await import(agenteLocalModule("command-dispatcher.js"));

  const token = await getToken();
  let allowedRoots = cfg.allowedRoots || [];
  const confirmFn = createNativeConfirm();

  wsConnection = createAgentConnection({
    backendUrl: cfg.backendUrl,
    token,
    onEvent: (evt) => {
      if (evt.type === "policy_update") allowedRoots = evt.allowed_roots || [];
      lastStatusLabel = { open: "conectado", close: "desconectado", connecting: "conectando…", unauthorized: "token inválido" }[evt.type] || lastStatusLabel;
      tray?.setToolTip(`JARVIS Agente Local — ${lastStatusLabel}`);
      rebuildTrayMenu();
    },
    onCommand: createCommandHandler({
      getAllowedRoots: () => allowedRoots,
      confirmFn,
      sendAudit: (entry) => wsConnection.sendAudit(entry),
      isUnlocked: () => false,
    }),
  });
}

app.whenReady().then(async () => {
  createSplash();
  createTray();
  try {
    const { auditLogPath } = await import(agenteLocalModule("config.js"));
    auditPath = auditLogPath();
    rebuildTrayMenu();
  } catch { /* ainda mostra a bandeja mesmo se isto falhar — item fica desabilitado */ }
  try {
    let cfg = null;
    try {
      cfg = await runPairingFlow();
    } catch (err) {
      dialog.showErrorBox("Pareamento não concluído", `${err.message}\n\nO Agente Local fica na bandeja, mas sem conexão até você parear (clique no ícone da bandeja de novo pra tentar).`);
    }
    if (cfg) {
      await connectAgent(cfg).catch((err) => dialog.showErrorBox("Falha ao conectar o Agente Local", err.message));
    }
  } finally {
    closeSplash();
  }
});

app.on("before-quit", () => {
  wsConnection?.close();
});

// Sem janela nenhuma pra fechar — o app inteiro é a bandeja. Sair só pelo
// menu da bandeja (ou Cmd+Q), nunca por "última janela fechada".
app.on("window-all-closed", () => {});
