/**
 * O CÉREBRO DE SEGURANÇA do Agente Local. Puro, sem I/O de rede, testável.
 *
 * Classifica cada ação numa das 4 camadas de risco (docs/SEGURANCA-AGENTE-LOCAL.md
 * Seções 6, 8, 9). A DECISÃO é sempre daqui — do PC — nunca do backend. Um erro
 * sutil neste arquivo é a diferença entre um sandbox e uma execução remota de
 * código, então cada regra abaixo tem um porquê e é coberta por teste.
 *
 * Tier 0 — leitura segura dentro das roots         -> automático
 * Tier 1 — escrita nas roots + comando na allowlist -> automático, auditado
 * Tier 2 — fora do padrão / caminho suspeito / shell -> pergunta local
 * Tier 3 — destrutivo / persistência                 -> bloqueado sempre
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

export const TIER = { READ: 0, WRITE: 1, CONFIRM: 2, BLOCK: 3 };

// --- Allowlist de comandos (Tier 1 — roda automático). Seção 6. ---
// Casadas contra o comando já normalizado (trim + espaços colapsados).
const ALLOWLIST = [
  /^dir(\s|$)/i, /^ls(\s|$)/i, /^pwd$/i, /^cd\s/i,
  /^mkdir\s/i, /^copy\s/i, /^cp\s/i, /^move\s/i,
  /^ren\s/i, /^rename\s/i, /^type\s/i, /^cat\s/i, /^echo\s/i,
  /^npm\s+(install|run|ci)(\s|$)/i, /^node\s/i,
  /^git\s+(status|log|diff|add|commit|pull|push|clone)(\s|$)/i,
  /^python3?(\s|$)/i, /^pip\s+install(\s|$)/i,
];

// --- Blocklist dura (Tier 3 — nunca roda sem liberação explícita). Seção 6. ---
const BLOCKLIST = [
  /format\s+[a-z]:/i,
  /\bdiskpart\b/i,
  /\brm\s+-rf?\s+[/~]/i,
  /\bdel\s+\/[sq]\s+[a-z]:\\/i,
  /\bshutdown\b/i,
  /\brestart-computer\b/i,
  /\breg\s+delete\s+HKLM/i,
  /\bSet-ExecutionPolicy\b/i,
  /\bnetsh\s/i,
  /Disable-.*(Defender|Firewall)/i,
  /\bschtasks\s+\/create\b/i,
  /\bsc\s+create\b/i,
  /(curl|iwr|wget|Invoke-WebRequest).*\|\s*(bash|sh|iex|Invoke-Expression)/i,
  /\bmkfs(\.\w+)?\b/i,
  /:\(\)\s*\{.*\}\s*;/,  // fork bomb :(){ :|:& };:
];

// Metacaracteres que só o shell interpreta. Presença => precisa de shell =>
// no MÍNIMO Tier 2 (Seção 9). É isto que quebra `mkdir a && curl evil|bash`.
const SHELL_METACHARS = /[;&|`$><\n]|\$\(|\|\|/;

// Nomes de arquivo/pasta sensíveis: mesmo LEITURA, mesmo dentro de uma root,
// sobe pra Tier 2 no mínimo (Seção 8 — denylist de caminhos).
const SENSITIVE_SEGMENTS = [
  ".ssh", ".aws", ".gnupg", ".env", ".git-credentials",
  "id_rsa", "id_ed25519", "credentials", "wallet.dat",
];
const SENSITIVE_PATH_FRAGMENTS = [
  path.join("System32", "config"),      // SAM/registry hives
  path.join("Login Data"),              // cofres de senha do Chrome/Edge
  path.join("logins.json"),             // cofre do Firefox
];

/**
 * Resolve `..` E symlinks até o ancestral existente mais próximo, depois anexa
 * a parte que ainda não existe (ex.: arquivo a criar). Sem isso, o truque
 * `Downloads/link-pro-system32/x` ou `Downloads/../../Windows` escaparia do
 * sandbox. Seção 8.
 */
export function canonicalize(target) {
  let cur = path.resolve(expandHome(target));
  const tail = [];
  // Sobe até achar um ancestral que existe de verdade, resolvendo symlinks nele.
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      const real = fs.realpathSync(cur);
      return tail.length ? path.join(real, ...tail.reverse()) : real;
    } catch {
      const parent = path.dirname(cur);
      if (parent === cur) {
        // Chegou na raiz sem nada existir — devolve o resolvido sintático.
        return tail.length ? path.join(cur, ...tail.reverse()) : cur;
      }
      tail.push(path.basename(cur));
      cur = parent;
    }
  }
}

function expandHome(p) {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/") || p.startsWith("~\\")) return path.join(os.homedir(), p.slice(2));
  return p;
}

/** true se `canonical` é a própria root ou está dentro dela (não só prefixo textual). */
function isWithin(canonical, root) {
  const r = path.resolve(root);
  if (canonical === r) return true;
  const rel = path.relative(r, canonical);
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
}

function hasSensitiveSegment(canonical) {
  const lower = canonical.toLowerCase();
  const segs = canonical.split(/[/\\]+/).map((s) => s.toLowerCase());
  if (SENSITIVE_SEGMENTS.some((s) => segs.includes(s.toLowerCase()))) return true;
  return SENSITIVE_PATH_FRAGMENTS.some((f) => lower.includes(f.toLowerCase()));
}

/**
 * Classifica uma operação de arquivo.
 * @param {string} rawPath  caminho pedido (pode ter ~, .., não existir ainda)
 * @param {string[]} allowedRoots  pastas raiz permitidas
 * @param {"read"|"write"} mode
 * @returns {{tier:number, reason:string, canonical:string}}
 */
export function classifyPath(rawPath, allowedRoots, mode = "read") {
  if (!rawPath || typeof rawPath !== "string") {
    return { tier: TIER.CONFIRM, reason: "caminho vazio ou inválido", canonical: "" };
  }
  const canonical = canonicalize(rawPath);
  const roots = (allowedRoots || []).map((r) => canonicalize(r));
  const inside = roots.some((r) => isWithin(canonical, r));

  if (!inside) {
    return { tier: TIER.CONFIRM, reason: "fora das pastas permitidas", canonical };
  }
  if (hasSensitiveSegment(canonical)) {
    // Segredo dentro de uma root: leitura já pergunta (Seção 8).
    return { tier: TIER.CONFIRM, reason: "caminho sensível (segredo/credencial)", canonical };
  }
  if (mode === "read") return { tier: TIER.READ, reason: "leitura dentro das roots", canonical };
  return { tier: TIER.WRITE, reason: "escrita dentro das roots", canonical };
}

/**
 * Classifica um comando de sistema.
 * Ordem: Tier 3 (blocklist) vence tudo -> shell metachar sobe pra >=2 ->
 * allowlist = Tier 1 -> resto = Tier 2. Seções 6 e 9.
 * @returns {{tier:number, reason:string}}
 */
export function classifyCommand(rawCommand) {
  if (!rawCommand || typeof rawCommand !== "string") {
    return { tier: TIER.CONFIRM, reason: "comando vazio" };
  }
  const cmd = rawCommand.trim().replace(/\s+/g, " ");

  for (const re of BLOCKLIST) {
    if (re.test(cmd)) return { tier: TIER.BLOCK, reason: `comando bloqueado (${re.source})` };
  }
  const needsShell = SHELL_METACHARS.test(rawCommand);
  if (needsShell) {
    // Encadeamento/redirecionamento: no mínimo confirma, mesmo que as partes
    // pareçam inofensivas. É o que impede `mkdir a && <coisa ruim>`.
    return { tier: TIER.CONFIRM, reason: "usa shell (encadeia/redireciona) — precisa confirmar" };
  }
  for (const re of ALLOWLIST) {
    if (re.test(cmd)) return { tier: TIER.WRITE, reason: "comando na allowlist" };
  }
  return { tier: TIER.CONFIRM, reason: "comando fora da allowlist" };
}

/**
 * Quebra um comando em [programa, ...args] SEM shell, respeitando aspas.
 * É isto que vai pro execFile/spawn (shell:false) — Seção 9. Se o comando
 * contém metacaractere de shell, devolve null: quem chama NÃO deve tentar
 * executar (subiu pra Tier 2, exige confirmação e caminho especial).
 * @returns {string[]|null}
 */
export function parseCommand(rawCommand) {
  if (SHELL_METACHARS.test(rawCommand)) return null;
  const tokens = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(rawCommand)) !== null) {
    tokens.push(m[1] ?? m[2] ?? m[3]);
  }
  return tokens.length ? tokens : null;
}

/** Nome legível do tier, pra UI/auditoria. */
export function tierName(tier) {
  return ["leitura-segura", "escrita-auto", "confirmar", "bloqueado"][tier] ?? "desconhecido";
}
