"""Estructura y salida comunes a los scripts de validación (solo biblioteca estándar)."""

from __future__ import annotations

import os
from dataclasses import dataclass

ERROR = "error"
WARNING = "aviso"


@dataclass(frozen=True)
class Finding:
    """Un problema encontrado en un archivo del repositorio."""

    path: str
    line: int  # 0 cuando no aplica a una línea concreta
    level: str  # ERROR o WARNING
    message: str

    def as_text(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.level}: {self.message}"

    def as_github_annotation(self) -> str:
        command = "error" if self.level == ERROR else "warning"
        location = f"file={self.path}"
        if self.line:
            location += f",line={self.line}"
        message = self.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        return f"::{command} {location}::{message}"


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def report(findings: list[Finding], label: str, *, strict: bool = False) -> int:
    """Imprime los hallazgos y devuelve el código de salida: 0 todo bien, 1 si hay fallos.

    Con strict=True los avisos también cuentan como fallo. Dentro de GitHub Actions los
    hallazgos se imprimen como anotaciones, que aparecen junto al archivo en el commit o PR.
    """
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for finding in sorted(findings, key=lambda f: (f.path, f.line, f.level, f.message)):
        print(finding.as_github_annotation() if annotate else finding.as_text())
    errors = sum(1 for f in findings if f.level == ERROR)
    warnings = len(findings) - errors
    print(f"{label}: {_plural(errors, 'error', 'errores')}, {_plural(warnings, 'aviso', 'avisos')}")
    return 1 if errors or (strict and warnings) else 0
