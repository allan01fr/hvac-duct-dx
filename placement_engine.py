"""Compatibilidade: o código mora em ductdx/difusores/motor_posicionamento.py."""
import sys

from ductdx.difusores import motor_posicionamento as _modulo

sys.modules[__name__] = _modulo
