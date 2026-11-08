"""Compatibilidade: o código mora em ductdx/difusores/dados_catalogo.py."""
import sys

from ductdx.difusores import dados_catalogo as _modulo

sys.modules[__name__] = _modulo
