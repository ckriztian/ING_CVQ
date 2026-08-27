"""Exportador desacoplado de Instrucciones de Trabajo mediante Excel COM."""

import importlib
import math
import platform
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Protocol


EXPORT_UNAVAILABLE = "La exportación Excel todavía no está disponible en este entorno."
PROCEDURE_SHEET = "Fijación cable de masa."
PROCEDURES_PER_PAGE = 2  # confirmado por los bloques C:Q y R:AF de la hoja auditada
MAX_MATERIALS = 4
MAX_TOOLS = 4
EXAMPLE_PROCEDURE_OBJECTS = {
    "Imagen 72", "Imagen 75", "Imagen 67", "Imagen 63", "Imagen 59",
    "16 Conector recto de flecha", "Elipse 71", "Rectángulo 86", "Rectangle 8",
    "36 Conector recto de flecha", "Conector: angular 98", "Elipse 82",
    "Flecha a la derecha con bandas 40", "Rectángulo 91", "Conector: angular 92",
}
EPP_MARK_CELLS = {
    "Pulsera": "A42", "Talonera": "E42", "Cofia": "I42", "Guantes": "M42",
    "Zapatos de Seguridad": "Q42", "Protección Auditiva": "U42",
    "Anteojos de Seguridad": "Y42", "Máscara de seguridad": "AC42",
}


class ExportError(RuntimeError):
    """Error controlado durante una exportación."""


class BackendUnavailableError(ExportError):
    pass


class WorkInstructionExporter(Protocol):
    def available(self) -> bool: ...
    def export(self, instruction: Dict[str, Any], revision_code: Optional[str] = None,
               output_dir: Optional[Path] = None) -> Path: ...


def safe_filename(document_code: str, revision_code: str, title: str) -> str:
    revision = revision_code.strip()
    if not revision.upper().startswith("R"):
        revision = "R" + revision
    raw = f"{document_code}_{revision}_{title}"
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", ascii_name)
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip(" ._")
    ascii_name = re.sub(r"_+", "_", ascii_name)
    return (ascii_name[:180] or "Instruccion_de_Trabajo") + ".xlsx"


def _win32_client():
    """Importación intencionalmente lazy para mantener compatible Linux."""
    return importlib.import_module("win32com.client")


def _pythoncom():
    return importlib.import_module("pythoncom")


class ExcelComWorkInstructionExporter:
    def __init__(self, template_path: Path, image_root: Path):
        self.template_path = Path(template_path)
        self.image_root = Path(image_root)

    def availability(self) -> tuple[bool, str]:
        if platform.system() != "Windows":
            return False, "Microsoft Excel COM requiere Windows"
        if not self.template_path.is_file():
            return False, "No se encontró la plantilla corporativa"
        try:
            client = _win32_client()
            pythoncom = _pythoncom()
        except (ImportError, ModuleNotFoundError):
            return False, "pywin32 no está instalado"
        excel = None
        try:
            pythoncom.CoInitialize()
            excel = client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            return True, "Excel COM disponible"
        except Exception as exc:
            return False, f"Microsoft Excel COM no está accesible: {exc}"
        finally:
            if excel is not None:
                try:
                    excel.Quit()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def available(self) -> bool:
        return self.availability()[0]

    def export(self, instruction: Dict[str, Any], revision_code: Optional[str] = None,
               output_dir: Optional[Path] = None) -> Path:
        if platform.system() != "Windows":
            raise BackendUnavailableError(EXPORT_UNAVAILABLE)
        if not self.template_path.is_file():
            raise ExportError("No se encontró la plantilla corporativa de Instrucciones de Trabajo.")
        try:
            client = _win32_client()
            pythoncom = _pythoncom()
        except (ImportError, ModuleNotFoundError) as exc:
            raise BackendUnavailableError(EXPORT_UNAVAILABLE) from exc

        revision = self._select_revision(instruction, revision_code)
        self._validate_capacity(revision)
        destination_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="it_export_"))
        destination_dir.mkdir(parents=True, exist_ok=True)
        output_path = destination_dir / safe_filename(instruction["document_code"], revision["revision_code"], revision["title"])
        working_dir = Path(tempfile.mkdtemp(prefix="it_com_work_"))
        working_copy = working_dir / "working_copy.xlsx"
        shutil.copy2(self.template_path, working_copy)

        excel = workbook = None
        try:
            pythoncom.CoInitialize()
            excel = client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Open(str(working_copy.resolve()), ReadOnly=False, UpdateLinks=0)
            pages = self._prepare_pages(excel, workbook, revision)
            for page_number, worksheet in enumerate(pages, 1):
                self._clean_example_content(worksheet)
                self._write_header(worksheet, instruction, revision, page_number, len(pages))
                self._write_procedures(worksheet, revision, page_number)
                self._write_materials(worksheet, revision["materials"])
                self._write_tools(worksheet, revision["tools"])
                self._write_epp(worksheet, revision["epp"])
            workbook.SaveAs(str(output_path.resolve()), FileFormat=51)
            workbook.Close(SaveChanges=False)
            workbook = None
            return output_path
        except BackendUnavailableError:
            raise
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            raise ExportError(f"No se pudo generar el Excel: {exc}") from exc
        finally:
            if workbook is not None:
                try:
                    workbook.Close(SaveChanges=False)
                except Exception:
                    pass
            if excel is not None:
                try:
                    excel.Quit()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            shutil.rmtree(working_dir, ignore_errors=True)

    @staticmethod
    def _select_revision(instruction: Dict[str, Any], revision_code: Optional[str]) -> Dict[str, Any]:
        if revision_code:
            revision = next((item for item in instruction["revisions"] if item["revision_code"] == revision_code), None)
            if not revision:
                raise ExportError("La revisión solicitada no existe.")
            return revision
        return instruction["current_revision"]

    @staticmethod
    def _validate_capacity(revision: Dict[str, Any]) -> None:
        if len(revision.get("materials", [])) > MAX_MATERIALS:
            raise ExportError(f"La plantilla admite {MAX_MATERIALS} materiales por IT; reduzca o divida la lista antes de exportar.")
        if len(revision.get("tools", [])) > MAX_TOOLS:
            raise ExportError(f"La plantilla admite {MAX_TOOLS} herramientas por IT; reduzca o divida la lista antes de exportar.")

    def _prepare_pages(self, excel: Any, workbook: Any, revision: Dict[str, Any]) -> list[Any]:
        first = workbook.Worksheets(PROCEDURE_SHEET)
        page_count = max(1, math.ceil(len(revision.get("steps", [])) / PROCEDURES_PER_PAGE))
        pages = [first]
        first.Name = "IT Página 1"
        for number in range(2, page_count + 1):
            pages[-1].Copy(After=pages[-1])
            copied = excel.ActiveSheet
            copied.Name = f"IT Página {number}"
            pages.append(copied)
        return pages

    @staticmethod
    def _clean_example_content(worksheet: Any) -> None:
        # Borrado por nombre OOXML/COM auditado: nunca por proximidad.
        for index in range(worksheet.Shapes.Count, 0, -1):
            shape = worksheet.Shapes.Item(index)
            if shape.Name in EXAMPLE_PROCEDURE_OBJECTS:
                shape.Delete()
        for address in ("C30", "C31", "C32", "C33", "R30", "R31", "R32", "R33", "C34"):
            worksheet.Range(address).ClearContents()

    @staticmethod
    def _write_header(worksheet: Any, instruction: Dict[str, Any], revision: Dict[str, Any], page: int, total: int) -> None:
        values = {
            "I1": f"N° {instruction['document_code']}", "A4": revision["area"],
            "C4": instruction.get("model_label", instruction["model_id"]), "I3": revision["process"],
            "O2": revision["prepared_by"], "S2": revision["reviewed_by"],
            "O3": revision["document_date"], "S3": revision["document_date"],
            "U3": revision.get("distribution") or "", "M4": revision["title"],
            "AC5": revision["revision_code"], "Z5": page, "AB5": total,
        }
        if revision.get("approved_by"):
            values["M1"] = f"APROBADO POR INGENIERÍA DE PRODUCCIÓN · {revision['approved_by']}"
        for cell, value in values.items():
            worksheet.Range(cell).Value = value

    def _write_procedures(self, worksheet: Any, revision: Dict[str, Any], page_number: int) -> None:
        start = (page_number - 1) * PROCEDURES_PER_PAGE
        steps = revision.get("steps", [])[start:start + PROCEDURES_PER_PAGE]
        slots = (
            {"title": "C6", "image": "C7:Q29", "instruction": "C30", "observation": "C31", "warning": "C32"},
            {"title": "R6", "image": "R7:AF29", "instruction": "R30", "observation": "R31", "warning": "R32"},
        )
        for slot_index, slot in enumerate(slots):
            absolute = start + slot_index
            step = steps[slot_index] if slot_index < len(steps) else None
            worksheet.Range(slot["title"]).Value = f"PASO {absolute + 1}" if step else ""
            for field in ("instruction", "observation", "warning"):
                worksheet.Range(slot[field]).Value = (step.get(field) or "") if step else ""
            if step and step.get("image"):
                self._insert_image(worksheet, slot["image"], step["image"])

    def _insert_image(self, worksheet: Any, target_address: str, image: Dict[str, Any]) -> None:
        relative = Path(image["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ExportError("La ruta de una imagen de procedimiento no es segura.")
        source = (self.image_root / relative).resolve()
        if self.image_root.resolve() not in source.parents or not source.is_file():
            raise ExportError(f"No se encontró la imagen del procedimiento: {relative.name}")
        target = worksheet.Range(target_address)
        shape = worksheet.Shapes.AddPicture(str(source), False, True, target.Left, target.Top, -1, -1)
        shape.LockAspectRatio = -1
        scale = min(target.Width / shape.Width, target.Height / shape.Height, 1.0)
        shape.Width = shape.Width * scale
        shape.Height = shape.Height * scale
        shape.Left = target.Left + (target.Width - shape.Width) / 2
        shape.Top = target.Top + (target.Height - shape.Height) / 2

    @staticmethod
    def _write_materials(worksheet: Any, materials: list[Dict[str, Any]]) -> None:
        for offset in range(MAX_MATERIALS):
            row = 37 + offset
            item = materials[offset] if offset < len(materials) else {}
            for column, field in (("S", "reference"), ("T", "description"), ("AA", "code"), ("AE", "quantity")):
                worksheet.Range(f"{column}{row}").Value = item.get(field, "")

    @staticmethod
    def _write_tools(worksheet: Any, tools: list[Dict[str, Any]]) -> None:
        for offset in range(MAX_TOOLS):
            row = 37 + offset
            item = tools[offset] if offset < len(tools) else {}
            for column, field in (("C", "description"), ("H", "specification"), ("O", "quantity")):
                worksheet.Range(f"{column}{row}").Value = item.get(field, "")

    @staticmethod
    def _write_epp(worksheet: Any, epp: list[Dict[str, Any]]) -> None:
        selected = {item["name"]: bool(item.get("selected")) for item in epp}
        for name, cell in EPP_MARK_CELLS.items():
            worksheet.Range(cell).Value = "x" if selected.get(name, False) else ""


class UnavailableExporter:
    message = EXPORT_UNAVAILABLE

    def available(self) -> bool:
        return False

    def export(self, instruction: Dict[str, Any], revision_code: Optional[str] = None,
               output_dir: Optional[Path] = None) -> Path:
        raise BackendUnavailableError(self.message)


BASE_DIR = Path(__file__).resolve().parent
exporter: WorkInstructionExporter = ExcelComWorkInstructionExporter(
    BASE_DIR / "templates" / "it" / "BSIP_IT_template.xlsx",
    BASE_DIR / "data" / "work_instructions",
)
