"""Smoke test manual del exportador COM; no usa la base de datos real."""

import platform
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from work_instruction_exporter import ExcelComWorkInstructionExporter  # noqa: E402


def fixture() -> dict:
    revision = {
        "revision_code": "R_TEST", "status": "draft", "area": "A. A.",
        "process": "PRUEBA COM", "title": "Validación exportador COM",
        "prepared_by": "Ingeniería", "reviewed_by": "Calidad", "approved_by": None,
        "document_date": date.today().isoformat(), "distribution": "PR (L3)",
        "steps": [
            {"position": 1, "instruction": "Tomar componente de prueba.", "observation": "Sin fotografía.", "warning": None, "image": None},
            {"position": 2, "instruction": "Verificar correcta fijación.", "observation": None, "warning": "Documento de prueba.", "image": None},
            {"position": 3, "instruction": "Registrar el resultado.", "observation": None, "warning": None, "image": None},
        ],
        "materials": [{"reference": "a", "description": "Material de prueba", "code": "TEST-001", "quantity": "1"}],
        "tools": [{"description": "Herramienta de prueba", "specification": "N/A", "quantity": "1"}],
        "epp": [{"name": "Pulsera", "selected": True}, {"name": "Zapatos de Seguridad", "selected": True}],
    }
    return {
        "instruction_id": "IT-TEST-COM", "model_id": "mdl_test", "model_label": "MODELO DE PRUEBA COM",
        "document_code": "BSIP IT TEST COM", "current_revision": revision, "revisions": [revision],
    }


def main() -> int:
    if platform.system() != "Windows":
        print("ERROR: este script requiere Windows.")
        return 1
    template = ROOT / "templates" / "it" / "BSIP_IT_template.xlsx"
    exporter = ExcelComWorkInstructionExporter(template, ROOT / "data" / "work_instructions")
    available, detail = exporter.availability()
    if not available:
        print(f"ERROR: {detail}")
        return 1
    output_dir = ROOT / "exports_test"
    output = exporter.export(fixture(), "R_TEST", output_dir)

    # Segunda apertura independiente: comprueba que Excel reconoce el resultado.
    import pythoncom
    import win32com.client
    excel = workbook = None
    try:
        pythoncom.CoInitialize()
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Open(str(output.resolve()), ReadOnly=True, UpdateLinks=0)
        workbook.Close(SaveChanges=False)
        workbook = None
    finally:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()
    print(f"OK: archivo generado y reabierto mediante Excel COM:\n{output.resolve()}")
    print("PENDIENTE: abrir manualmente y certificar la presentación visual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
