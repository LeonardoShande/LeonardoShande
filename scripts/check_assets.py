#!/usr/bin/env python3
"""Comprueba que los archivos de assets/ estén íntegros y sean seguros de publicar.

Por cada archivo de la carpeta:

- .svg: XML bien formado con raíz <svg>. Avisa si contiene <script> o manejadores de
  eventos (onload, onclick...). Si declara entidades XML (<!ENTITY ...>) no lo analiza,
  porque pueden usarse para expandir el contenido, y lo avisa.
- .png, .jpg, .jpeg, .gif, .webp: el contenido debe ser realmente una imagen (no un puntero
  de Git LFS ni un archivo cortado). Un PNG se recorre bloque a bloque hasta IEND. Si la
  extensión no coincide con el contenido (un JPEG llamado .png) solo avisa.
- Avisa de los archivos que pesan más de 5 MiB y de los que el README no menciona.

Uso:
    python scripts/check_assets.py [--assets assets] [--readme README.md] [--strict]

Código de salida: 0 todo bien (o no existe la carpeta), 1 hay errores.
Solo usa la biblioteca estándar de Python.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from findings import ERROR, WARNING, Finding, report

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_SIZE = 5 * 1024 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
RASTER_KINDS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}
CHECKED_EXTENSIONS = {".svg", *RASTER_KINDS}


def sniff_image(data: bytes) -> str | None:
    """Detecta el formato real de una imagen por sus primeros bytes."""
    if data.startswith(PNG_SIGNATURE):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def png_problem(data: bytes) -> str | None:
    """Recorre los bloques de un PNG; devuelve el problema encontrado o None si está completo."""
    position = len(PNG_SIGNATURE)
    first = True
    while position + 8 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        end = position + 8 + length + 4  # cabecera + datos + CRC
        if end > len(data):
            return "PNG cortado: un bloque termina más allá del final del archivo"
        if first and kind != b"IHDR":
            return "PNG sin bloque de cabecera IHDR"
        first = False
        if kind == b"IEND":
            return None
        position = end
    return "PNG incompleto: falta el bloque final IEND"


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def check_svg(data: bytes) -> list[tuple[str, str]]:
    """Devuelve una lista de (nivel, mensaje) para el contenido de un SVG."""
    if b"<!ENTITY" in data:
        return [(WARNING, "declara entidades XML (<!ENTITY>): no se analizó por seguridad; quítalas si no las necesitas")]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return [(ERROR, f"SVG mal formado: {exc}")]
    if _local(root.tag) != "svg":
        return [(ERROR, f"la raíz del XML es <{_local(root.tag)}>, no <svg>")]
    problems = []
    if any(_local(element.tag) == "script" for element in root.iter()):
        problems.append((WARNING, "contiene <script>: GitHub no lo ejecuta, pero conviene quitarlo"))
    if any(_local(attribute).startswith("on") for element in root.iter() for attribute in element.attrib):
        problems.append((WARNING, "contiene manejadores de eventos (onload, onclick...): conviene quitarlos"))
    return problems


def check_file(path: Path, root: Path, max_size: int = DEFAULT_MAX_SIZE) -> list[Finding]:
    """Revisa un archivo de assets y devuelve sus problemas."""
    relative = path.relative_to(root).as_posix()
    extension = path.suffix.lower()
    if extension not in CHECKED_EXTENSIONS:
        return []
    data = path.read_bytes()
    if not data:
        return [Finding(relative, 0, ERROR, "el archivo está vacío")]
    if data.startswith(LFS_POINTER):
        return [Finding(relative, 0, ERROR, "es un puntero de Git LFS, no la imagen real")]

    problems: list[tuple[str, str]] = []
    if extension == ".svg":
        problems.extend(check_svg(data))
    else:
        actual = sniff_image(data)
        if actual is None:
            problems.append((ERROR, f"no parece una imagen {extension[1:]} válida (¿corrupta o cortada?)"))
        else:
            if actual != RASTER_KINDS[extension]:
                problems.append((WARNING, f"la extensión es {extension} pero el contenido es {actual}"))
            if actual == "png":
                detail = png_problem(data)
                if detail:
                    problems.append((ERROR, detail))
    if len(data) > max_size:
        megabytes = len(data) / 1024 / 1024
        problems.append((WARNING, f"pesa {megabytes:.1f} MiB (más de {max_size / 1024 / 1024:.0f} MiB): conviene optimizarlo"))
    return [Finding(relative, 0, level, message) for level, message in problems]


def check_assets(
    root: Path, assets: str = "assets", readme: str = "README.md", max_size: int = DEFAULT_MAX_SIZE
) -> list[Finding]:
    """Revisa todos los archivos de la carpeta de assets (lista vacía si todo está bien)."""
    root = Path(root)
    folder = root / assets
    if not folder.is_dir():
        return []
    readme_path = root / readme
    readme_text = None
    if readme_path.is_file():
        readme_text = readme_path.read_text(encoding="utf-8-sig", errors="replace").lower()

    findings: list[Finding] = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        findings.extend(check_file(path, root, max_size))
        if readme_text is not None and path.suffix.lower() in CHECKED_EXTENSIONS:
            name = path.name.lower()
            if name not in readme_text and quote(name).lower() not in readme_text:
                findings.append(
                    Finding(path.relative_to(root).as_posix(), 0, WARNING, f"no se menciona en {readme}: ¿sobra?")
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba que las imágenes de assets/ estén íntegras.")
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="raíz del repositorio (por defecto, la carpeta que contiene scripts/)"
    )
    parser.add_argument("--assets", default="assets", help="carpeta de assets dentro de la raíz")
    parser.add_argument("--readme", default="README.md", help="README donde se buscan las menciones a cada archivo")
    parser.add_argument("--max-size-mb", type=float, default=DEFAULT_MAX_SIZE / 1024 / 1024, help="peso máximo antes de avisar")
    parser.add_argument("--strict", action="store_true", help="los avisos también hacen fallar el script")
    args = parser.parse_args(argv)

    if not (args.root / args.assets).is_dir():
        print(f"{args.assets}/: no existe, no hay nada que revisar")
        return 0
    findings = check_assets(args.root, args.assets, args.readme, int(args.max_size_mb * 1024 * 1024))
    return report(findings, f"{args.assets}/", strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
