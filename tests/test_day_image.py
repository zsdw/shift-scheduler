"""주간 현장 양식 이미지 다운로드 (2026-10-07): PNG 생성·업로드 칸 옆 버튼 (PC·폰)."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift.day_shift import DayPerson, attach_trainees, number_people, solve_day
from night_shift.day_image import render_day_png

ROOT = Path(__file__).resolve().parent.parent
DAY = date(2026, 10, 8)
NAMES = ("만년", "광희", "제욱", "원종", "도운", "성욱", "용주", "준호")


class DayImageTests(unittest.TestCase):
    def test_png_with_trainee_and_cp(self):
        s, status = solve_day(DAY, number_people([DayPerson(n, n, "출근") for n in NAMES] + [DayPerson("여진", "여진", "교육")]),
                              trainees={"여진": "준호"})
        self.assertIsNotNone(s, status)
        png = render_day_png(s, {"1": "이덕영", "2": "안철룡", "3": "권혁준"})
        self.assertTrue(png.startswith(b"\x89PNG"))
        s = attach_trainees(s, {"여진": "A"})
        self.assertTrue(render_day_png(s).startswith(b"\x89PNG"))

    def test_download_button_on_saved_day_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                (Path(folder) / "day").mkdir()
                data = json.loads((ROOT / "tests" / "fixtures" / "day_2026-10-08_saved.json").read_text(encoding="utf-8"))
                (Path(folder) / "day" / "2026-10-08.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = DAY
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                labels = [b.label for b in at.get("download_button")] + [b.label for b in at.button]
                self.assertTrue(any(l.startswith("🖼 현장 양식 이미지") for l in labels), labels)
                self.assertIn("📊 현장 양식 엑셀 다운로드", labels)            # 원본 양식 엑셀 (2026-10-11)


class ShuttleColorTests(unittest.TestCase):
    def test_shuttle_cell_uses_number_color(self):
        import io
        from PIL import Image
        from night_shift.day_shift import NUMBER_COLORS, DaySchedule
        from day_ui import _shuttle_text_cell
        people = tuple(DayPerson(n, n, "출근", i + 1) for i, n in enumerate(NAMES))
        s = DaySchedule(DAY, people, {p.pid: ["휴게"] * 10 for p in people}, {0: "광희"}, control=False)
        im = Image.open(io.BytesIO(render_day_png(s))).convert("RGB")
        x, y = (80 + 72 * 10 + 36) * 2, (201 + 4) * 2           # 08시 셔틀 칸
        self.assertEqual("%02X%02X%02X" % im.getpixel((x, y)), NUMBER_COLORS[2])
        self.assertIn(f"#{NUMBER_COLORS[5]}", _shuttle_text_cell("5(해지)"))  # 업로드 원본 글자도 색
        self.assertIn("#92D050", _shuttle_text_cell("CP3"))            # 17시 셔틀 CP3 = CP3 색
        from night_shift.day_image import cp_color
        # 원본 10/7·10/8 대조: 혼자면 그 CP 색, 여럿이면 CP2 → CP3 → CP1
        self.assertEqual([cp_color(x) for x in ("CP1", "CP2", "CP3", "CP1.CP2", "CP2.CP3", "CP1.CP3", "11.CP3", "")],
                         ["70AD47", "00B0F0", "92D050", "00B0F0", "00B0F0", "92D050", "92D050", None])


if __name__ == "__main__":
    unittest.main()
