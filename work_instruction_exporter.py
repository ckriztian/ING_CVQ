"""Contrato desacoplado para futuros exportadores de Instrucciones de Trabajo."""

from pathlib import Path
from typing import Any, Dict, Protocol


class WorkInstructionExporter(Protocol):
    def available(self) -> bool: ...
    def export(self, instruction: Dict[str, Any]) -> Path: ...


class UnavailableExporter:
    message = "La exportación Excel todavía no está disponible en este entorno."

    def available(self) -> bool:
        return False

    def export(self, instruction: Dict[str, Any]) -> Path:
        raise RuntimeError(self.message)


exporter: WorkInstructionExporter = UnavailableExporter()
