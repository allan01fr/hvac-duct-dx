"""Compatibilidade: o código mora em ductdx/difusores/adaptador_posicionamento.py."""
import sys

from ductdx.difusores import adaptador_posicionamento as _modulo

sys.modules[__name__] = _modulo
