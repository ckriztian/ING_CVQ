from pathlib import Path
from types import SimpleNamespace

import pytest

import work_instruction_exporter as module
from work_instruction_exporter import CellOperationError, ExcelComWorkInstructionExporter, ExportError
from work_instruction_exporter import _clear_cell, _set_cell_value, safe_filename


def instruction(step_count=3):
    revision = {
        "revision_code": "R1", "area": "AA", "process": "Montaje", "title": "Fijación Panel divisor 2",
        "prepared_by": "A", "reviewed_by": "B", "approved_by": None, "document_date": "2026-08-27",
        "distribution": "L3", "steps": [{"instruction": f"Paso {n}", "observation": None, "warning": None, "image": None} for n in range(step_count)],
        "materials": [], "tools": [], "epp": [], "status": "active",
    }
    return {"instruction_id": "IT-000001", "model_id": "mdl_1", "model_label": "12K · MIDEA · INV",
            "document_code": "BSIP IT UOA4874", "current_revision": revision, "revisions": [revision]}


class FakeCells:
    def __init__(self, anchor): self.anchor = anchor
    def __call__(self, row, column):
        assert (row, column) == (1, 1)
        return self.anchor


class FakeRange:
    Left, Top, Width, Height = 0, 0, 500, 300
    def __init__(self, address="", merged=False, merge_area=None):
        self.Value, self.Address, self.MergeCells = None, address, merged
        self.clear_count = 0
        self.MergeArea = merge_area or self
        self.Cells = FakeCells(self)
    def ClearContents(self): self.Value = None; self.clear_count += 1


class FakeMergeArea(FakeRange):
    def __init__(self, address):
        super().__init__(address)
        self.anchor = FakeRange(address.split(":")[0])
        self.Cells = FakeCells(self.anchor)


class FakeShape:
    def __init__(self, name, owner): self.Name, self.owner, self.deleted = name, owner, False
    def Delete(self): self.deleted = True; self.owner.items.remove(self)


class FakeShapes:
    def __init__(self): self.items = [FakeShape("Imagen 72", self), FakeShape("58 Imagen", self), FakeShape("Elipse 71", self)]
    @property
    def Count(self): return len(self.items)
    def Item(self, index): return self.items[index - 1]


class FakeSheet:
    def __init__(self, excel, name=module.PROCEDURE_SHEET):
        self.excel, self.Name, self.Shapes, self.cells = excel, name, FakeShapes(), {}
    def Range(self, address): return self.cells.setdefault(address, FakeRange(address))
    def Copy(self, After=None):
        copied = FakeSheet(self.excel)
        self.excel.workbook.sheets.append(copied)
        self.excel.ActiveSheet = copied


class FakeWorksheets:
    def __init__(self, excel): self.excel = excel
    def __call__(self, name): return next(x for x in self.excel.workbook.sheets if x.Name == name)


class FakeWorkbook:
    def __init__(self, excel):
        self.excel, self.closed, self.saved = excel, False, None
        self.sheets = [FakeSheet(excel)]
        self.Worksheets = FakeWorksheets(excel)
    def SaveAs(self, path, FileFormat): self.saved = Path(path); self.saved.write_bytes(b"fake-xlsx")
    def Close(self, SaveChanges=False): self.closed = True


class FakeWorkbooks:
    def __init__(self, excel): self.excel = excel
    def Open(self, path, **kwargs):
        self.excel.workbook = FakeWorkbook(self.excel)
        return self.excel.workbook


class FakeExcel:
    def __init__(self):
        self.Visible, self.DisplayAlerts, self.quit_called = True, True, False
        self.Workbooks = FakeWorkbooks(self); self.ActiveSheet = None; self.workbook = None
    def Quit(self): self.quit_called = True


class FakeClient:
    def __init__(self): self.instances = []
    def DispatchEx(self, progid):
        assert progid == "Excel.Application"
        excel = FakeExcel(); self.instances.append(excel); return excel


def test_safe_windows_filename():
    assert safe_filename("BSIP IT UOA4874", "R1", "Fijación: Panel/Divisor 2") == "BSIP_IT_UOA4874_R1_Fijacion_Panel_Divisor_2.xlsx"
    assert ".." not in safe_filename("../IT", "2", "a*b?")


def test_availability_is_false_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    exporter = ExcelComWorkInstructionExporter(tmp_path / "missing.xlsx", tmp_path)
    assert exporter.available() is False


def test_com_export_copies_template_paginates_cleans_and_quits(monkeypatch, tmp_path):
    template = tmp_path / "template.xlsx"; template.write_bytes(b"original")
    client = FakeClient()
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_win32_client", lambda: client)
    monkeypatch.setattr(module, "_pythoncom", lambda: SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None))
    exporter = ExcelComWorkInstructionExporter(template, tmp_path / "images")
    output = exporter.export(instruction(), "R1", tmp_path / "output")
    excel = client.instances[0]
    assert output.read_bytes() == b"fake-xlsx"
    assert template.read_bytes() == b"original"
    assert len(excel.workbook.sheets) == 2
    assert all("Imagen 72" not in [shape.Name for shape in sheet.Shapes.items] for sheet in excel.workbook.sheets)
    assert all("58 Imagen" in [shape.Name for shape in sheet.Shapes.items] for sheet in excel.workbook.sheets)
    assert excel.workbook.sheets[0].Range("Z5").Value == 1
    assert excel.workbook.sheets[1].Range("Z5").Value == 2
    assert excel.workbook.closed and excel.quit_called


def test_capacity_errors_are_explicit(tmp_path):
    exporter = ExcelComWorkInstructionExporter(tmp_path / "template.xlsx", tmp_path)
    data = instruction(1)
    data["current_revision"]["materials"] = [{"description": "x"}] * 4
    with pytest.raises(ExportError, match="3 materiales"):
        exporter._validate_capacity(data["current_revision"])


def test_safe_write_supports_normal_and_merged_cells_without_unmerge():
    worksheet = FakeSheet(None, "IT")
    normal = FakeRange("A1")
    area = FakeMergeArea("B2:D2")
    merged = FakeRange("C2", merged=True, merge_area=area)
    worksheet.cells.update({"A1": normal, "B2:D2": merged})
    _set_cell_value(worksheet, "A1", "normal", "normal_field")
    _set_cell_value(worksheet, "B2:D2", "merged", "merged_field")
    assert normal.Value == "normal"
    assert area.anchor.Value == "merged"
    assert not hasattr(area, "UnMerge") and not hasattr(merged, "UnMerge")


def test_safe_clear_uses_merge_area_once_and_normal_range_once():
    worksheet = FakeSheet(None, "IT")
    normal = FakeRange("A1")
    area = FakeMergeArea("B2:D2")
    merged_a = FakeRange("B2", merged=True, merge_area=area)
    merged_b = FakeRange("C2", merged=True, merge_area=area)
    worksheet.cells.update({"A1": normal, "B2": merged_a, "C2": merged_b})
    cleared = set()
    _clear_cell(worksheet, "A1", "normal", cleared)
    _clear_cell(worksheet, "B2", "merged_a", cleared)
    _clear_cell(worksheet, "C2", "merged_b", cleared)
    assert normal.clear_count == 1 and area.clear_count == 1


def test_cell_error_contains_operation_context():
    worksheet = FakeSheet(None, "IT Página 1")
    broken = FakeRange("C30:Q30")
    broken.MergeCells = True
    broken.MergeArea = property(lambda self: None)
    worksheet.cells["C30:Q30"] = broken
    with pytest.raises(CellOperationError) as caught:
        _set_cell_value(worksheet, "C30:Q30", "text", "procedure_1_instruction")
    assert caught.value.field == "procedure_1_instruction"
    assert caught.value.sheet == "IT Página 1"
    assert caught.value.address == "C30:Q30"
    assert caught.value.operation == "write"


def test_procedures_materials_tools_and_pagination_use_safe_writer(monkeypatch):
    calls = []
    monkeypatch.setattr(module, "_set_cell_value", lambda ws, address, value, field: calls.append((address, field, value)))
    exporter = ExcelComWorkInstructionExporter(Path("template"), Path("images"))
    data = instruction(2); revision = data["current_revision"]
    revision["materials"] = [{"reference": "a", "description": "Tornillo", "code": "1", "quantity": "2"}]
    revision["tools"] = [{"description": "Atornilladora", "specification": "PH2", "quantity": "1"}]
    worksheet = FakeSheet(None, "IT")
    exporter._write_header(worksheet, data, revision, 1, 2)
    exporter._write_procedures(worksheet, revision, 1)
    exporter._write_materials(worksheet, revision["materials"])
    exporter._write_tools(worksheet, revision["tools"])
    fields = {field for _, field, _ in calls}
    assert {"page", "page_total", "procedure_1_instruction", "material_1_description", "tool_1_description"} <= fields
    assert ("T37:Z38", "material_1_description", "Tornillo") in calls
