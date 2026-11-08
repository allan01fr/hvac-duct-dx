#!/usr/bin/env python3
"""Constrói o banco do catálogo (hvac_equipment.sqlite, esquema v2) a partir das planilhas em data/.

Toda a lógica está em `ductdx.catalogo.carregador`; este arquivo só lê a linha de comando.
O banco é montado num arquivo temporário e só substitui o destino se tudo passar.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import tempfile
from collections.abc import Sequence
from pathlib import Path

from ductdx.catalogo.carregador import construir_banco
from ductdx.catalogo.fontes.qdmt import BuildError

LOGGER = logging.getLogger("build_db")
RAIZ = Path(__file__).resolve().parent
DATA_DIR_PADRAO = RAIZ / "data"
BANCO_PADRAO = RAIZ / "hvac_equipment.sqlite"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR_PADRAO,
                        help=f"Pasta das planilhas (padrão: {DATA_DIR_PADRAO})")
    parser.add_argument("--db", type=Path, default=BANCO_PADRAO,
                        help=f"Banco de saída (padrão: {BANCO_PADRAO})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Constrói e valida num temporário, sem substituir o banco")
    parser.add_argument("--verbose", action="store_true", help="Log detalhado")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    try:
        if args.dry_run:
            with tempfile.TemporaryDirectory() as pasta:
                construir_banco(args.data_dir, Path(pasta) / args.db.name)
            LOGGER.info("Dry-run concluído; %s não foi alterado", args.db)
        else:
            construir_banco(args.data_dir, args.db)
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2
    except (BuildError, OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.error("Falha na construção: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
