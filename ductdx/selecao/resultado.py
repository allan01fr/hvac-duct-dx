"""Saída da seleção: uma linha por modelo e o pacote completo com rastreabilidade."""
from dataclasses import dataclass

from ductdx.selecao.requisitos import Requeridos, Requisitos


@dataclass(frozen=True)
class ResultadoModelo:
    adequado: bool
    pontuacao: float
    modelo: str
    classe_kbtu: float
    capacidade_total_btuh: float
    capacidade_sensivel_btuh: float
    vazao_cfm: float
    alimentacao: str
    modelo_interno: str
    modelo_externo: str
    dimensoes_internas_mm: str
    ruido_dba: float
    velocidade: str
    capacidade_aquecimento_btuh: float
    motivos: str
    catalogo: str
    eer_btu_wh: float | None
    metadados_vazao: dict

    def como_linha_legada(self) -> tuple:
        """Tupla de 18 itens, na ordem que App.render() já entende."""
        return (self.adequado, self.pontuacao, self.modelo, self.classe_kbtu,
                self.capacidade_total_btuh, self.capacidade_sensivel_btuh,
                self.vazao_cfm, self.alimentacao, self.modelo_interno,
                self.modelo_externo, self.dimensoes_internas_mm, self.ruido_dba,
                self.velocidade, self.capacidade_aquecimento_btuh, self.motivos,
                self.catalogo, self.eer_btu_wh, self.metadados_vazao)


@dataclass(frozen=True)
class ResultadoSelecao:
    requisitos: Requisitos
    requeridos: Requeridos
    linhas: list[ResultadoModelo]
    avisos: list[str]
    versao_motor: str
    versao_catalogo: str | None
