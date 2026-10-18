"""2026-10-04: 주간 근무표도 야간처럼 표에서 끌어서(폰은 눌러서) 근무 교환."""
import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift.day_shift import (PATROL, REST, edit_day, load_day, save_day, solve_day, validate_day)
from tests.test_day_shift import people

APP = str(Path(__file__).resolve().parents[1] / "app.py")
DAY = date(2026, 10, 7)


def schedule():
    s, status = solve_day(DAY, people({"도운": "연차", "만년": "오후반차"}), seconds=20)
    assert s is not None, status
    return s


class EditDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = schedule()

    def pair(self, t=1):
        ids = [pid for pid, row in self.s.grid.items() if row[t] is not None and row[t] != self.s.grid[next(iter(self.s.grid))][t]]
        a = next(pid for pid, row in self.s.grid.items() if row[t] is not None)
        b = next(pid for pid, row in self.s.grid.items() if row[t] is not None and row[t] != self.s.grid[a][t])
        return a, b

    def test_swap_same_hour_and_reject_other_hour_or_unavailable(self):
        a, b = self.pair()
        new = edit_day(self.s, {"kind": "swap", "a": [a, 1], "b": [b, 1]})
        self.assertEqual((new.grid[a][1], new.grid[b][1]), (self.s.grid[b][1], self.s.grid[a][1]))
        self.assertNotEqual(self.s.grid[a][1], new.grid[a][1])                # 원본은 그대로
        with self.assertRaises(ValueError):
            edit_day(self.s, {"kind": "swap", "a": [a, 1], "b": [b, 2]})       # 다른 시간끼리 금지
        with self.assertRaises(ValueError):                                    # 오후반차(13시 퇴근) 오후 칸
            edit_day(self.s, {"kind": "swap", "a": ["만년", 7], "b": [a, 7]})
        locked = type(self.s)(**{**self.s.__dict__, "locked_through": 2})
        with self.assertRaises(ValueError):
            edit_day(locked, {"kind": "swap", "a": [a, 1], "b": [b, 1]})      # LOCK 시간 금지

    def test_move_into_column_and_row_swap(self):
        t = 4
        worker = next(pid for pid, row in self.s.grid.items() if row[t] not in (None, REST))
        moved = edit_day(self.s, {"kind": "move", "a": [worker, t], "col": REST, "t": t})
        self.assertEqual(moved.grid[worker][t], REST)
        patroller = next((pid for pid, row in self.s.grid.items() if row[1] == PATROL), None)
        rest = next(pid for pid, row in self.s.grid.items() if row[1] == REST)
        if patroller:                                                          # 사람이 있는 순찰 칸으로 → 맞바꿈
            swapped = edit_day(self.s, {"kind": "move", "a": [rest, 1], "col": PATROL, "t": 1})
            self.assertEqual((swapped.grid[rest][1], swapped.grid[patroller][1]), (PATROL, REST))
        full = [pid for pid, row in self.s.grid.items() if None not in row]
        rows = edit_day(self.s, {"kind": "rowswap", "a": full[0], "b": full[1]})
        self.assertEqual(rows.grid[full[0]], self.s.grid[full[1]])
        with self.assertRaises(ValueError):                                    # 반차자와 전일근무자는 하루 교환 금지
            edit_day(self.s, {"kind": "rowswap", "a": "만년", "b": full[0]})


def grid_event(event):
    return patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True,
                 side_effect=lambda component, **kw: event if component.name.endswith("day_sheet") else None)


class DayDragUiTests(unittest.TestCase):
    def test_generated_and_saved_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                at = AppTest.from_file(APP, default_timeout=150)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = DAY
                at.run()
                at.button(key="day_generate").click().run()
                base = at.session_state["day_results"][0]
                a = next(pid for pid, row in base.grid.items() if row[1] is not None)
                b = next(pid for pid, row in base.grid.items() if row[1] is not None and row[1] != base.grid[a][1])
                before = (base.grid[a][1], base.grid[b][1])
                with grid_event({"kind": "swap", "a": [a, 1], "b": [b, 1], "nonce": f"g-{view}"}):
                    at.run()
                self.assertFalse(at.exception)
                after = at.session_state["day_results"][0]
                changed = (after.grid[a][1], after.grid[b][1]) == (before[1], before[0])
                self.assertTrue(changed or any("꼭 지킬 규칙" in e.value for e in at.error))   # 반영 또는 거절 이유
                if changed:
                    self.assertEqual(validate_day(after), [])                  # 생성표는 하드룰 유지
                # 저장본: 경고만, 💾 저장으로 파일 반영
                saved = schedule()
                save_day(Path(folder) / "day", saved)
                at2 = AppTest.from_file(APP, default_timeout=150)
                at2.query_params["view"] = view
                at2.run()
                at2.session_state["shift_date"] = DAY
                at2.run()
                key = f"saved_{DAY}_base_0"
                worker = next(pid for pid, row in saved.grid.items() if row[4] not in (None, REST))
                with grid_event({"kind": "move", "a": [worker, 4], "col": REST, "t": 4, "nonce": f"s-{view}"}):
                    at2.run()
                self.assertFalse(at2.exception)
                at2.button(key=f"day_save_actual_{key}").click().run()
                self.assertFalse(at2.exception)
                self.assertEqual(load_day(Path(folder) / "day", DAY)["schedule"].grid[worker][4], REST)


class JpegImportTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows 문자 인식 필요")
    def test_compressed_phone_image_reads_like_png(self):
        from PIL import Image
        from night_shift import history_import as imp
        from night_shift.schedule_image import render_png
        from tests.test_history_import import field_book, record
        png = render_png(record(imp.parse_excel(field_book(), "야간")))
        buf = io.BytesIO()
        Image.open(io.BytesIO(png)).convert("RGB").resize((1999, 1420)).save(buf, "JPEG", quality=50)
        self.assertEqual(imp.parse_image(buf.getvalue()).grid, imp.parse_image(png).grid)


if __name__ == "__main__":
    unittest.main()
