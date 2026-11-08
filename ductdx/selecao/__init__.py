"""Seleção de equipamentos: ESP, verificação de forro e motor de seleção."""
from ductdx.selecao.catalogo import (
    Catalogo,
    CatalogoIndisponivel,
    ModeloCatalogo,
    PontoResfriamento,
    PontoVazao,
)
from ductdx.selecao.catalogo_prefixo import CatalogoPorPrefixo
from ductdx.selecao.familias import (
    FAMILIAS,
    Familia,
    familia_por_codigo,
    familia_por_rotulo,
)
from ductdx.selecao.motor import resolver_velocidade, selecionar
from ductdx.selecao.requisitos import (
    FASES,
    VELOCIDADES,
    ParametrosForro,
    Requeridos,
    Requisitos,
    aplicar_margens,
    temperatura_de_catalogo,
)
from ductdx.selecao.resultado import ResultadoModelo, ResultadoSelecao

__all__ = [
    "FAMILIAS", "FASES", "VELOCIDADES", "Catalogo", "CatalogoIndisponivel",
    "CatalogoPorPrefixo", "Familia", "ModeloCatalogo", "ParametrosForro",
    "PontoResfriamento", "PontoVazao", "Requeridos", "Requisitos",
    "ResultadoModelo", "ResultadoSelecao", "aplicar_margens", "familia_por_codigo",
    "familia_por_rotulo", "resolver_velocidade", "selecionar",
    "temperatura_de_catalogo",
]
