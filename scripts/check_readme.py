#!/usr/bin/env python3
"""Comprueba que el README no apunte a archivos que no existen en el repositorio.

Revisa imágenes y enlaces escritos en Markdown (![alt](ruta), [texto](ruta),
[id]: ruta) y en HTML (src, href, srcset, poster):

- Rutas relativas (assets/logo.svg, ./a.png, /assets/a.png): el archivo debe existir.
- Enlaces absolutos de GitHub a ESTE repositorio
  (https://github.com/OWNER/REPO/raw/main/assets/a.svg; también blob, tree y
  raw.githubusercontent.com): se resuelven contra los archivos del disco. Para saber cuál
  es "este repositorio" se usa --repo o, si falta, la variable GITHUB_REPOSITORY (GitHub
  Actions ya la define).
- El resto de enlaces externos no se revisan aquí: de eso se encarga lychee
  (.github/workflows/links.yml).

Se ignoran los bloques de código, el código en línea y los comentarios HTML. Los avisos
(imagen sin texto alternativo, enlace que sale del repositorio) no hacen fallar el script
salvo con --strict.

Uso:
    python scripts/check_readme.py [--readme README.md] [--repo OWNER/REPO] [--strict]

Código de salida: 0 todo bien, 1 hay errores, 2 no se encontró el README.
Solo usa la biblioteca estándar de Python.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

from findings import ERROR, WARNING, Finding, report

REPO_ROOT = Path(__file__).resolve().parent.parent

# "](destino)", "](destino "título")" o "](<destino con espacios>)". Sirve para imágenes y
# para enlaces, también anidados: [![alt](imagen)](enlace).
MD_TARGET = re.compile(r"\]\([ \t]*(?:<([^>\n]*)>|([^)\s]*))[^)\n]*\)")
# ![alt](...): solo para avisar de imágenes sin texto alternativo.
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(")
# [id]: destino "título"   (las notas al pie, [^1]: texto, no cuentan)
REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*<?([^\s>]+)>?", re.MULTILINE)
HTML_ATTR = re.compile(r"""\b(src|href|srcset|poster)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
ALT_ATTR = re.compile(r"\balt\s*=", re.IGNORECASE)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
FENCE_OPEN = re.compile(r"`{3,}|~{3,}")

GITHUB_FILE_KINDS = {"raw", "blob", "tree", "blame"}


def _blank(match: re.Match[str]) -> str:
    """Sustituye el texto por espacios conservando los saltos de línea."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_non_content(text: str) -> str:
    """Quita comentarios HTML, bloques de código y código en línea sin mover las líneas."""
    text = HTML_COMMENT.sub(_blank, text)
    out: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        stripped = line.lstrip()
        if fence is None:
            opening = FENCE_OPEN.match(stripped)
            if opening:
                fence = opening.group(0)
                out.append("")
            else:
                out.append(INLINE_CODE.sub(_blank, line))
        else:
            if stripped.startswith(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _github_url_paths(url: str, repo: str | None) -> list[str]:
    """Rutas (relativas a la raíz) a las que apunta una URL de GitHub de ESTE repositorio.

    Devuelve una lista vacía si la URL no apunta a un archivo de este repositorio.
    """
    if not repo or repo.count("/") != 1:
        return []
    try:
        split = urlsplit(url)
    except ValueError:
        return []
    host = (split.hostname or "").lower()
    parts = [unquote(p) for p in split.path.split("/") if p]
    owner_repo = [p.lower() for p in repo.split("/")]

    if host in {"github.com", "www.github.com"}:
        if len(parts) < 5 or [p.lower() for p in parts[:2]] != owner_repo or parts[2] not in GITHUB_FILE_KINDS:
            return []
        rest = parts[3:]
    elif host == "raw.githubusercontent.com":
        if len(parts) < 4 or [p.lower() for p in parts[:2]] != owner_repo:
            return []
        rest = parts[2:]
    else:
        return []
    # El primer tramo es la rama; si tuviera "/" (feature/x, refs/heads/main) se prueban
    # todos los cortes posibles.
    return ["/".join(rest[i:]) for i in range(1, len(rest))]


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _is_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _iter_targets(clean: str) -> Iterator[tuple[int, str]]:
    """Genera (línea, destino) de cada imagen o enlace del texto ya limpio."""
    for match in MD_TARGET.finditer(clean):
        yield _line_of(clean, match.start()), match.group(1) or match.group(2) or ""
    for match in REF_DEF.finditer(clean):
        target = match.group(1)
        # "[ES]: Hola" no es un enlace: se exige que parezca una ruta o una URL.
        if "/" in target or "." in target:
            yield _line_of(clean, match.start()), target
    for match in HTML_ATTR.finditer(clean):
        line = _line_of(clean, match.start())
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if name == "srcset":
            for candidate in value.split(","):
                fields = candidate.split()
                if fields:
                    yield line, fields[0]
        else:
            yield line, value


def _check_target(
    target: str, line: int, *, root: Path, base_dir: Path, readme: str, repo: str | None
) -> Finding | None:
    target = target.strip()
    if not target or target.startswith("#"):
        return None
    try:
        split = urlsplit(target)
    except ValueError:
        return None

    if split.scheme in {"http", "https"}:
        candidates = _github_url_paths(target, repo)
        if candidates and not any(_exists(root / c) for c in candidates):
            return Finding(
                readme, line, ERROR, f"el enlace apunta a este repositorio pero no existe el archivo: {candidates[0]}"
            )
        return None
    if split.scheme or split.netloc:
        return None  # mailto:, tel:, data:, //servidor/..., C:\...

    path = unquote(split.path)
    if not path:
        return None
    base = root if path.startswith("/") else base_dir
    candidate = base / path.lstrip("/")
    if not _is_inside(root, candidate):
        # GitHub permite enlaces como ../../issues; por eso es un aviso y no un error.
        return Finding(readme, line, WARNING, f"apunta fuera del repositorio: {target}")
    if not _exists(candidate):
        return Finding(readme, line, ERROR, f"no existe el archivo: {path}")
    return None


def _alt_warnings(clean: str, readme: str) -> list[Finding]:
    findings = []
    for match in MD_IMAGE.finditer(clean):
        if not match.group(1).strip():
            findings.append(Finding(readme, _line_of(clean, match.start()), WARNING, "imagen sin texto alternativo (alt)"))
    for match in HTML_IMG.finditer(clean):
        if not ALT_ATTR.search(match.group(0)):
            findings.append(Finding(readme, _line_of(clean, match.start()), WARNING, "<img> sin atributo alt"))
    return findings


def check_readme(root: Path, readme: str = "README.md", repo: str | None = None) -> list[Finding]:
    """Devuelve los problemas del README (lista vacía si todo está bien)."""
    root = Path(root)
    readme_path = root / readme
    text = readme_path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        return [Finding(readme, 1, ERROR, "el README está vacío")]

    clean = _strip_non_content(text)
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for line, target in _iter_targets(clean):
        if (line, target) in seen:
            continue
        seen.add((line, target))
        finding = _check_target(
            target, line, root=root, base_dir=readme_path.parent, readme=readme, repo=repo
        )
        if finding:
            findings.append(finding)
    findings.extend(_alt_warnings(clean, readme))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba que el README no apunte a archivos inexistentes del repositorio."
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="raíz del repositorio (por defecto, la carpeta que contiene scripts/)"
    )
    parser.add_argument("--readme", default="README.md", help="ruta del README dentro de la raíz")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="OWNER/REPO de este repositorio, para resolver enlaces absolutos de GitHub (por defecto, $GITHUB_REPOSITORY)",
    )
    parser.add_argument("--strict", action="store_true", help="los avisos también hacen fallar el script")
    args = parser.parse_args(argv)

    if not (args.root / args.readme).is_file():
        print(f"{args.readme}: error: no existe en {args.root}", file=sys.stderr)
        return 2
    findings = check_readme(args.root, args.readme, args.repo)
    return report(findings, args.readme, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
