"""Gerador de PDF mínimo, só com a biblioteca padrão.

Escreve texto corrido em Helvetica (WinAnsiEncoding, aceita acentos do
português), com quebra de linha e de página automáticas. Não tem data de
criação no arquivo: a mesma entrada gera exatamente os mesmos bytes.
"""
from __future__ import annotations

import pathlib
import textwrap

LARGURA, ALTURA = 595, 842          # A4 em pontos
MARGEM = 56
LINHAS_POR_PAGINA = 58
COLUNAS = 92


def _escapar(txt: str) -> str:
    return txt.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _linhas(blocos: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Converte blocos (estilo, texto) em linhas (estilo, linha) já quebradas."""
    saida: list[tuple[str, str]] = []
    for estilo, texto in blocos:
        if estilo == "espaco":
            saida.append(("normal", ""))
            continue
        largura = COLUNAS if estilo == "normal" else int(COLUNAS * 0.8)
        for paragrafo in texto.split("\n"):
            partes = textwrap.wrap(paragrafo, largura) or [""]
            saida.extend((estilo, p) for p in partes)
    return saida


def escrever_pdf(caminho: pathlib.Path, blocos: list[tuple[str, str]]) -> None:
    """blocos: lista de (estilo, texto) com estilo em titulo|subtitulo|normal|espaco."""
    linhas = _linhas(blocos)
    paginas = [linhas[i:i + LINHAS_POR_PAGINA] for i in range(0, len(linhas), LINHAS_POR_PAGINA)] or [[]]

    objetos: list[bytes] = []

    def novo(conteudo: bytes) -> int:
        objetos.append(conteudo)
        return len(objetos)

    fonte = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    negrito = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    id_paginas = novo(b"")  # preenchido depois
    filhos = []
    tamanhos = {"titulo": 15, "subtitulo": 11.5, "normal": 10}
    for n, pagina in enumerate(paginas, 1):
        y = ALTURA - MARGEM
        cmds = []
        for estilo, linha in pagina:
            tam = tamanhos[estilo]
            f = "F2" if estilo in ("titulo", "subtitulo") else "F1"
            cmds.append(f"BT /{f} {tam} Tf {MARGEM} {y:.1f} Td ({_escapar(linha)}) Tj ET")
            y -= tam * 1.38
        cmds.append(f"BT /F1 8 Tf {LARGURA - MARGEM - 40} 30 Td (pág. {n}/{len(paginas)}) Tj ET")
        stream = "\n".join(cmds).encode("cp1252", errors="replace")
        conteudo = novo(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pag = novo(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (id_paginas, LARGURA, ALTURA, fonte, negrito, conteudo)
        )
        filhos.append(pag)
    objetos[id_paginas - 1] = (
        b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % f for f in filhos)
        + b"] /Count %d >>" % len(filhos)
    )
    catalogo = novo(b"<< /Type /Catalog /Pages %d 0 R >>" % id_paginas)

    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objetos, 1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for off in offsets:
        saida += b"%010d 00000 n \n" % off
    saida += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1, catalogo, xref)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(bytes(saida))
