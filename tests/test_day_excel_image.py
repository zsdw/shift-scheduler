"""주간 현장 양식을 원본 편성표 엑셀 양식으로 그리기 (2026-10-08): 칸 채우기 + (엑셀 있으면) 실제 그림."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from night_shift import day_excel_image as x
from night_shift.day_shift import DayPerson, attach_trainees, number_people, solve_day

DAY = date(2026, 10, 8)
NAMES = ("만년", "광희", "제욱", "원종", "도운", "성욱", "용주", "준호")
CP = {"1": "이덕영", "2": "안철룡", "3": "권혁준"}


def excel_available():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "$x=New-Object -ComObject Excel.Application; $x.Quit(); 'ok'"],
                             capture_output=True, text=True, timeout=60)
        return "ok" in out.stdout
    except (OSError, subprocess.SubprocessError):
        return False


class DayExcelImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        people = number_people([DayPerson(n, n, "출근") for n in NAMES] + [DayPerson("여진", "여진", "교육")])
        cls.schedule, status = solve_day(DAY, people, trainees={"여진": "준호"})
        assert cls.schedule is not None, status

    def test_layout_and_spec(self):
        lay = x.layout()
        self.assertEqual(lay["date_cell"], "A3")
        self.assertEqual(list(lay["hours"]), list(range(8, 18)))
        self.assertIn("셔틀", lay["columns"])
        with tempfile.TemporaryDirectory() as folder:
            spec = x.build_spec(self.schedule, Path(folder), CP)
        values = spec["values"]
        self.assertEqual(values["A3"], "2026년 10월 08일 목요일 근무조 : A조")
        row5 = [values.get(x._cell(5, c), "") for c in sorted(lay["columns"].values())]
        row6 = [values.get(x._cell(6, c), "") for c in sorted(lay["columns"].values())]
        self.assertTrue(row5[0].startswith("통제") or row5[0].startswith("1"))
        self.assertEqual(row6[0], "통제A")
        self.assertIn("CP1덕영", row6)
        self.assertIn("9여진", row5 + row6)
        cp_col = lay["columns"]["CP"]
        self.assertEqual(values[x._cell(lay["hours"][8], cp_col)], "CP1.CP2")
        self.assertEqual(values[x._cell(lay["hours"][17], lay["columns"]["셔틀"])], "CP3")
        edu = values[x._cell(lay["hours"][10], lay["columns"]["대기"])]
        self.assertTrue(edu.startswith("교육: "))

    def test_xlsx_download_keeps_original_form(self):
        """원본 양식 엑셀 다운로드 (2026-10-11): 서식·조건부 색은 양식 그대로, 칸은 이미지와 같은 값."""
        import io
        import openpyxl
        with tempfile.TemporaryDirectory() as folder:
            spec = x.build_spec(self.schedule, Path(folder), CP)
            book = openpyxl.load_workbook(io.BytesIO(x.to_xlsx(self.schedule, Path(folder), CP)))
        sheet, form = book.worksheets[0], openpyxl.load_workbook(x.FORM).worksheets[0]
        self.assertEqual(sheet.title, "26년10월08일(주)")
        self.assertEqual(len(sheet.conditional_formatting), len(form.conditional_formatting))
        self.assertEqual({str(m) for m in sheet.merged_cells.ranges}, {str(m) for m in form.merged_cells.ranges})
        for address, text in spec["values"].items():
            self.assertEqual(str(sheet[address].value), text)
        self.assertEqual(sheet["E23"].value, form["E23"].value)            # 원본 특이사항 문구 유지
        cleared = [a for a in spec["clear"] if a not in spec["values"] and sheet[a].value is not None
                   and type(sheet[a]).__name__ != "MergedCell"]
        self.assertEqual(cleared, [])                                       # 양식에 남은 예전 값 없음

    @unittest.skipUnless(excel_available(), "엑셀이 설치된 PC에서만")
    def test_render_with_excel_same_size_as_original(self):
        from PIL import Image
        import io
        with tempfile.TemporaryDirectory() as folder:
            png = x.render(self.schedule, Path(folder), CP)
            self.assertIsNotNone(png)
            im = Image.open(io.BytesIO(png)).convert("RGB")
            self.assertEqual(im.size, (1177, 686))             # 원본 편성표 이미지와 같은 크기
            colors = {c for _, c in im.getcolors(1_000_000)}
            self.assertIn((0, 176, 240), colors)               # 2번·CP 색 00B0F0 (엑셀 조건부 서식)
            self.assertIsNotNone(x.cached(self.schedule, Path(folder), CP))


class DayFormDrawTests(unittest.TestCase):
    def test_draw_without_excel_matches_original_rules(self):
        import io
        from PIL import Image
        from night_shift import day_form_draw as d
        self.assertTrue(d.available())
        # 원본 엑셀 조건부 서식 순서 그대로
        self.assertEqual([d.rule_color(v) for v in ("8.11", "7.9", "A.10", "CP1.CP3", "CP1", "4(설치)", "A", "")],
                         ["CC9900", "FF0000", "FFFFCC", "92D050", "70AD47", "EDEDED", None, None])
        lay = x.layout()
        spec = {x._cell(lay["hours"][8], lay["columns"]["G1"]): "7",
                x._cell(lay["hours"][8], lay["columns"]["대기"]): "8",
                x._cell(lay["hours"][8], lay["columns"]["휴게"]): "A.2"}
        im = Image.open(io.BytesIO(d.draw(spec, {c: k for k, c in lay["columns"].items()}))).convert("RGB")
        self.assertEqual(im.size, (1177, 686))                 # 원본과 같은 크기
        geo = __import__("json").loads(d.GEOMETRY.read_text(encoding="utf-8-sig"))["cells"]
        g1 = geo[x._cell(lay["hours"][8], lay["columns"]["G1"])]
        wait = geo[x._cell(lay["hours"][8], lay["columns"]["대기"])]
        rest = geo[x._cell(lay["hours"][8], lay["columns"]["휴게"])]
        px = lambda c, dx, dy: im.getpixel((round(c["left"] * d.PX) + dx, round(c["top"] * d.PX) + dy))
        self.assertEqual(px(g1, 6, 3), (0x7B, 0x7B, 0x7B))      # 7번 색 (원본 픽셀)
        self.assertEqual(px(wait, 1, 1), (0, 0x80, 0))          # 대기 숫자 칸 초록 삼각형
        self.assertEqual(px(rest, 6, 3), (255, 255, 255))      # 휴게는 흰 칸


if __name__ == "__main__":
    unittest.main()

