"""Leitores das fontes do catálogo (planilhas QDMT, Miraco e rooftop).

Cada leitor devolve `TabelasFamilia`: chave = nome da tabela antiga sem prefixo,
valor = linhas (dicts) com os nomes de coluna antigos. Nada é gravado aqui.
Estes módulos podem usar pandas/openpyxl (exceção à regra de import do pacote).
"""

TabelasFamilia = dict[str, list[dict]]
