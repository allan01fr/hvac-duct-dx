# Gera a referência da seleção UMA vez a partir do main.py atual. Nunca regenerar.
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path[:0] = [str(RAIZ), str(AQUI)]

from casos_selecao import CASOS, caso_completo
from execucao_selecao import executar_legado, preparar_banco


def main():
    rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, text=True).strip()
    sha = hashlib.sha256((RAIZ / "hvac_equipment.sqlite").read_bytes()).hexdigest()
    casos = {}
    with tempfile.TemporaryDirectory() as tmp:
        for caso in CASOS:
            banco = preparar_banco(caso_completo(caso)["banco"], Path(tmp) / "b.sqlite")
            casos[caso["nome"]] = executar_legado(caso, banco)
    saida = {"gerado_de": f"main.py@{rev}", "banco_sha256": sha, "casos": casos}
    with open(AQUI / "referencia_selecao.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    print(len(casos), "casos")


if __name__ == "__main__":
    main()
