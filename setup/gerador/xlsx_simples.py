"""Escreve e lê .xlsx mínimos só com biblioteca padrão (zipfile + XML).

Escrita: uma aba, células de número ou texto. Datas entram como texto
("03/02/2026") ou como número de série do Excel (46071), do jeito que um
gerente de projeto deixaria a planilha. Os bytes saem sempre iguais (sem data
de criação), então a seed fixa gera o mesmo arquivo.

Leitura: só o necessário para o validar_padroes.py conferir a resposta.
"""
from __future__ import annotations

import datetime as dt
import io
import pathlib
import re
import zipfile
from xml.sax.saxutils import escape

_EPOCA_EXCEL = dt.date(1899, 12, 30)
_DATA_FIXA = (2026, 1, 1, 0, 0, 0)

_TIPOS = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
         '</Relationships>')
_WB_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>')


def serial_excel(d: dt.date) -> int:
    return (d - _EPOCA_EXCEL).days


def data_de_serial(n: float) -> dt.date:
    return _EPOCA_EXCEL + dt.timedelta(days=int(n))


def _coluna(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _celula(lin: int, col: int, v) -> str:
    ref = f"{_coluna(col)}{lin + 1}"
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'


def escrever_xlsx(caminho: pathlib.Path, linhas: list[list], aba: str = "Cronograma") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    corpo = "".join(f'<row r="{i + 1}">' + "".join(_celula(i, j, v) for j, v in enumerate(linha)) + "</row>"
                    for i, linha in enumerate(linhas))
    planilha = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{corpo}</sheetData></worksheet>')
    livro = ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             f'<sheets><sheet name="{escape(aba)}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    buf = io.BytesIO()            # monta em memória: o volume do Databricks não aceita escrita fora de ordem
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in (("[Content_Types].xml", _TIPOS), ("_rels/.rels", _RELS), ("xl/workbook.xml", livro),
                               ("xl/_rels/workbook.xml.rels", _WB_RELS), ("xl/worksheets/sheet1.xml", planilha)):
            info = zipfile.ZipInfo(nome, date_time=_DATA_FIXA)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, conteudo)
    caminho.write_bytes(buf.getvalue())


def ler_xlsx(caminho: pathlib.Path) -> list[list]:
    """Devolve as linhas da primeira aba (número como float, texto como str, vazio como None)."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(caminho) as z:
        raiz = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    linhas = []
    for row in raiz.iter(f"{{{ns['m']}}}row"):
        valores = {}
        for c in row.findall("m:c", ns):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + (ord(ch) - 64)
            if c.get("t") == "inlineStr":
                valores[idx - 1] = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
            else:
                v = c.find("m:v", ns)
                valores[idx - 1] = float(v.text) if v is not None else None
        n = max(valores) + 1 if valores else 0
        linhas.append([valores.get(i) for i in range(n)])
    return linhas
