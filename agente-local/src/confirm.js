/**
 * Confirmação NATIVA local (Seção 7 — a defesa contra injeção de prompt). Não
 * passa pelo backend: é uma janela/notificação do próprio SO, com o comando
 * CRU visível, e a escolha some sem nunca viajar pela rede até aqui.
 *
 * Implementa o `confirmFn` que safe-exec.js espera: recebe {command, reason,
 * tier, tierLabel, provenance} e resolve com "once" | "always" | "deny".
 * Fail-safe: qualquer erro, timeout, cancelamento ou ferramenta ausente vira
 * "deny" — nunca "once" por acidente.
 *
 * AVISO HONESTO: os três branches de SO (osascript/PowerShell/zenity) não têm
 * como ser exercitados de verdade neste ambiente — é um container Linux sem
 * display gráfico, sem zenity instalado, sem Windows nem macOS disponíveis.
 * A lógica de construção de mensagem e parsing de resposta é pura e está
 * testada; a chamada ao binário do SO em si precisa de um smoke test manual
 * na máquina real antes de ir pra produção (ver agente-local/README.md).
 */
import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const LABEL_ONCE = "Permitir uma vez";
const LABEL_ALWAYS = "Sempre permitir";
const LABEL_DENY = "Negar";

/** Texto mostrado na janela. O comando cru é a última linha de defesa — Seção 7. */
export function buildConfirmMessage({ command, reason, tierLabel, provenance }) {
  const lines = [
    `Ação: ${tierLabel || "requer confirmação"}`,
    `Motivo: ${reason || "fora do padrão configurado"}`,
    "",
    "Comando/ação exata pedida:",
    String(command),
  ];
  if (provenance?.chat_id) lines.push("", `Origem: conversa ${provenance.chat_id}`);
  return lines.join("\n");
}

/** Interpreta o texto devolvido pela ferramenta nativa numa das 3 escolhas. */
export function parseButtonLabel(text) {
  const t = String(text || "");
  if (t.includes(LABEL_ALWAYS)) return "always";
  if (t.includes(LABEL_ONCE)) return "once";
  if (t.includes(LABEL_DENY)) return "deny";
  return null;
}

function runNative(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { windowsHide: true, timeout: 120_000, ...opts }, (err, stdout, stderr) => {
      if (err) reject(Object.assign(err, { stdout: String(stdout || ""), stderr: String(stderr || "") }));
      else resolve({ stdout: String(stdout || ""), stderr: String(stderr || "") });
    });
  });
}

function appleScriptQuote(s) {
  return `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

async function confirmMac(message, run) {
  const script = [
    `display dialog ${appleScriptQuote(message)}`,
    `with title "JARVIS — confirmação"`,
    `buttons {${appleScriptQuote(LABEL_DENY)}, ${appleScriptQuote(LABEL_ALWAYS)}, ${appleScriptQuote(LABEL_ONCE)}}`,
    `default button ${appleScriptQuote(LABEL_ONCE)}`,
    `cancel button ${appleScriptQuote(LABEL_DENY)}`,
    `with icon caution`,
  ].join(" ");
  try {
    const { stdout } = await run("osascript", ["-e", script]);
    return parseButtonLabel(stdout) ?? "deny";
  } catch {
    return "deny"; // botão "Negar" (cancel button) faz o osascript "falhar" — é o caminho esperado
  }
}

function buildWindowsScript() {
  // WinForms simples: 3 botões, fecha como "deny" se a janela for fechada no X.
  // Mensagem vem por env var (evita quebrar a linha de comando com aspas).
  return `
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = "JARVIS - confirmacao"
$form.Width = 560; $form.Height = 280
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$form.FormBorderStyle = "FixedDialog"

$label = New-Object System.Windows.Forms.Label
$label.Text = $env:JARVIS_CONFIRM_MSG
$label.Left = 20; $label.Top = 20; $label.Width = 510; $label.Height = 160
$form.Controls.Add($label)

$script:result = "${LABEL_DENY}"

function New-Btn($text, $left, $value) {
  $b = New-Object System.Windows.Forms.Button
  $b.Text = $text; $b.Left = $left; $b.Top = 195; $b.Width = 165
  $b.Add_Click({ $script:result = $value; $form.Close() }.GetNewClosure())
  return $b
}
$form.Controls.Add((New-Btn "${LABEL_DENY}" 20 "${LABEL_DENY}"))
$form.Controls.Add((New-Btn "${LABEL_ALWAYS}" 195 "${LABEL_ALWAYS}"))
$btnOnce = New-Btn "${LABEL_ONCE}" 370 "${LABEL_ONCE}"
$form.Controls.Add($btnOnce)
$form.AcceptButton = $btnOnce

[void]$form.ShowDialog()
Write-Output $script:result
`.trim();
}

async function confirmWindows(message, run) {
  const scriptPath = path.join(os.tmpdir(), `jarvis-confirm-${Date.now()}-${Math.random().toString(36).slice(2)}.ps1`);
  fs.writeFileSync(scriptPath, buildWindowsScript(), "utf8");
  try {
    const { stdout } = await run(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath],
      { env: { ...process.env, JARVIS_CONFIRM_MSG: message } }
    );
    return parseButtonLabel(stdout) ?? "deny";
  } catch {
    return "deny";
  } finally {
    fs.rm(scriptPath, { force: true }, () => {});
  }
}

async function confirmLinux(message, run) {
  try {
    const { stdout } = await run("zenity", [
      "--question",
      "--title=JARVIS — confirmação",
      `--text=${message}`,
      `--ok-label=${LABEL_ONCE}`,
      `--cancel-label=${LABEL_DENY}`,
      `--extra-button=${LABEL_ALWAYS}`,
    ]);
    // zenity: OK sai com código 0 (sem stdout útil) -> "once"; extra-button
    // sai com código 1 mas IMPRIME o rótulo do botão no stdout.
    return parseButtonLabel(stdout) ?? "once";
  } catch (err) {
    // Cancel (ou "Negar") também sai com código != 0, mas sem stdout que bata
    // com nenhum rótulo -> cai em "deny" abaixo. zenity ausente cai aqui também.
    return parseButtonLabel(err?.stdout) ?? "deny";
  }
}

/**
 * @param {object} [opts]
 * @param {string} [opts.platform]   força a plataforma (teste); default os.platform()
 * @param {(cmd:string,args:string[],opts?:object)=>Promise<{stdout:string,stderr:string}>} [opts.run]  injetável (teste)
 * @returns {(info:object)=>Promise<"once"|"always"|"deny">}
 */
export function createNativeConfirm({ platform = os.platform(), run = runNative } = {}) {
  return async function confirmFn(info) {
    const message = buildConfirmMessage(info);
    if (platform === "darwin") return confirmMac(message, run);
    if (platform === "win32") return confirmWindows(message, run);
    return confirmLinux(message, run);
  };
}
