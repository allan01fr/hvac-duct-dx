"""Compatibilidade: o código mora em ductdx/difusores/geometria_ambiente.py."""
import sys

from ductdx.difusores import geometria_ambiente as _modulo

sys.modules[__name__] = _modulo
