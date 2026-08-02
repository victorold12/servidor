#!/usr/bin/env python
"""Roda a suíte inteira do backend. Equivalente ao tests/executa.mjs do painel.

===========================================================================
POR QUE ISTO EXISTE

Rodar `python tests/test_x.py` um a um no Windows reprovava 6 de 23 testes —
todos com `UnicodeEncodeError: '\\u2713'`. Nenhum era defeito de lógica: os
testes imprimem "✓", e o console do Windows usa cp1252, que não tem esse
caractere. No CI (Linux, UTF-8) sempre passaram.

O efeito prático era pior que o incômodo: a suíte do backend não era executável
na máquina do Victor, que é justamente onde este projeto decidiu que se depura
melhor. Um teste que só roda na nuvem só é consultado depois de 20 minutos de
fila, e por isso deixa de ser consultado.

É a mesma família do `spawn('python3')` que impedia a suíte do painel de rodar
aqui: portabilidade de FERRAMENTA, não de produto. O produto estava certo o
tempo todo — quem não rodava era o teste.

===========================================================================
POR QUE UM CORREDOR, E NÃO 23 ARQUIVOS CORRIGIDOS

`sys.stdout.reconfigure(encoding='utf-8')` em cada teste resolveria, mas seria
a mesma linha repetida 23 vezes e esquecida no 24º. Aqui a decisão fica num
lugar só, e um teste novo nasce funcionando.

Uso:  python tests/roda.py            (tudo)
      python tests/roda.py memory     (só os que casam com "memory")
"""
import os
import pathlib
import subprocess
import sys

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent


def main() -> int:
    # O NOSSO stdout também, não só o do filho.
    #
    # Custou um susto: a primeira versão ajustava só o ambiente do subprocesso e
    # passou 23/23. Um teste que falha DE PROPÓSITO revelou o buraco — ao repetir
    # a saída do teste quebrado, o `print` daqui estourava no mesmo "✓". O
    # corredor funcionava exatamente enquanto não era preciso, que é quando uma
    # ferramenta de diagnóstico menos pode falhar.
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass          # fluxo redirecionado que não aceita: seguir é melhor que parar

    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    arquivos = sorted(p for p in AQUI.glob("test_*.py") if filtro in p.name)
    if not arquivos:
        print(f"nenhum teste casa com {filtro!r}")
        return 1

    # O ambiente do filho, não o nosso: é o `print` DELE que quebra.
    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    falhas = []
    for arq in arquivos:
        r = subprocess.run([sys.executable, str(arq)], cwd=RAIZ, env=ambiente,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print(f"  ok  {arq.name}")
        else:
            falhas.append(arq.name)
            print(f"FALHA {arq.name}")
            # A saída do teste que quebrou vale mais que qualquer resumo meu:
            # a causa está nela. Só as últimas linhas, que é onde ela aparece.
            cauda = (r.stdout + r.stderr).strip().splitlines()[-15:]
            for linha in cauda:
                print(f"        {linha}")

    print(f"\n{len(arquivos) - len(falhas)} passaram, {len(falhas)} falharam")
    if falhas:
        print("falhou: " + ", ".join(falhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
