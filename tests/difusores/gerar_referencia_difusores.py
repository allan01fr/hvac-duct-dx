# CONGELADO (proveniência): gerado uma única vez, a partir de diffuser_calculator.py na raiz (antes da mudança de pasta).
# A referência nunca é regenerada; se um teste falhar, o código está errado, não a referência.
import json
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path[:0] = [str(RAIZ), str(AQUI)]

from casos_difusores import CASOS, executar


def main():
    rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, text=True).strip()
    casos = {nome: executar(nome) for nome in CASOS}
    saida = {"gerado_de": f"diffuser_calculator.py@{rev}", "casos": casos}
    with open(AQUI / "referencia_difusores.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    print(len(casos), "casos")


if __name__ == "__main__":
    main()
