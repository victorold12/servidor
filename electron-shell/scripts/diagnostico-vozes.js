#!/usr/bin/env node
/**
 * Colhe OS FATOS de por que um motor de voz não ficou pronto. Só roda quando
 * algo já falhou, e imprime pouco de propósito.
 *
 * ---------------------------------------------------------------------------
 * POR QUE ISTO EXISTE
 *
 * Duas causas reais deste projeto eram invisíveis pelo sintoma:
 *
 *   - O Chatterbox morre com `TypeError: 'NoneType' object is not callable` em
 *     `perth.PerthImplicitWatermarker()`. Nada nessa mensagem diz "marca-d'água",
 *     e menos ainda diz POR QUE a classe é None: o `__init__` do `perth` engole
 *     o ImportError de verdade e deixa o nome valendo None. O erro que
 *     explicaria tudo é justamente o que o pacote joga fora.
 *
 *   - O Kokoro morria com "No module named uvicorn" — que parece defeito do
 *     Kokoro, e era instalação que nunca aconteceu (o projeto usa pyproject.toml
 *     e o instalador só sabia ler requirements.txt).
 *
 * A regra deste arquivo é não concluir nada: ele mostra o import cru, o
 * conteúdo do venv e o resumo que o próprio instalador escreveu. Foi chutar em
 * cima de sintoma — o nome da chave do `config.yaml` — que custou uma sessão
 * inteira antes.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { motoresEmDisco, raizDasVozes } from "../src/instalador-vozes.js";

const documentos = process.env.JARVIS_DOCUMENTOS || path.join(os.homedir(), "Documents");
const raiz = raizDasVozes(documentos);

const titulo = (s) => console.log(`\n=== ${s}`);

titulo("o que o instalador disse que ficou faltando");
const resumo = path.join(raiz, "resumo-da-instalacao.txt");
console.log(fs.existsSync(resumo) ? fs.readFileSync(resumo, "utf-8").trim() : "(sem resumo-da-instalacao.txt)");

/** Roda um python do venv e devolve saída+erro, sem deixar o processo morrer. */
function py(python, codigo) {
  const r = spawnSync(python, ["-c", codigo], { encoding: "utf-8", timeout: 120000 });
  return ((r.stdout || "") + (r.stderr || "")).trim() || `(sem saída, status ${r.status})`;
}

for (const m of motoresEmDisco(documentos)) {
  titulo(`${m.nome}`);
  console.log(`pasta:     ${m.pasta}`);
  console.log(`existe:    ${fs.existsSync(m.pasta)}`);
  console.log(`instalado: ${m.instalado}${m.instalado ? " (" + m.via + ")" : " — " + m.motivo}`);

  const python = process.platform === "win32"
    ? path.join(m.pasta, ".venv", "Scripts", "python.exe")
    : path.join(m.pasta, ".venv", "bin", "python");
  if (!fs.existsSync(python)) {
    console.log("sem python no venv — a instalação não chegou a criar o ambiente.");
    continue;
  }

  console.log("\n-- versões");
  console.log(py(python, "import sys;print('python',sys.version.split()[0])"));
  console.log(py(python, "import torch;print('torch',torch.__version__)"));
  console.log(py(python, "import torchvision,torchaudio;print('torchvision',torchvision.__version__,'torchaudio',torchaudio.__version__)"));

  if (m.id === "chatterbox") {
    /* O ponto exato do mistério: a classe é None, e o erro que explicaria isso
       foi engolido. Reimportar o submódulo faz o ImportError original aparecer. */
    console.log("\n-- perth (a marca-d'água que derruba o carregamento do modelo)");
    console.log(py(python, "import perth;print('PerthImplicitWatermarker =',perth.PerthImplicitWatermarker)"));
    console.log(py(python,
      "import importlib,traceback\n" +
      "for nome in ['perth.perth_net','perth.perth_net.perth_net_implicit','perth.utils']:\n" +
      "    try:\n" +
      "        importlib.import_module(nome); print('ok  ',nome)\n" +
      "    except Exception as e:\n" +
      "        print('ERRO',nome,'->',type(e).__name__,e)"));
    console.log(py(python, "import perth,os;print('perth em',os.path.dirname(perth.__file__));print(sorted(os.listdir(os.path.dirname(perth.__file__)))[:20])"));
  }

  if (m.id === "kokoro") {
    console.log("\n-- uvicorn e ponto de entrada");
    console.log(py(python, "import uvicorn;print('uvicorn',uvicorn.__version__)"));
    console.log(py(python, "import importlib;m=importlib.import_module('api.src.main');print('api.src.main importa, app =',getattr(m,'app',None) is not None)"));
    for (const f of ["pyproject.toml", "requirements.txt", "server.py"]) {
      console.log(`${f}: ${fs.existsSync(path.join(m.pasta, f))}`);
    }
  }
}
