"""2026-10-13 사용자 요청: 💒 웨딩 있는 날 직접 입력·표시(표기만), 야간 비고의 막타임(07시) 휴게 섞임·분배."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from night_shift import history_import as imp, history_store, wedding
from night_shift.models import Mode

ROOT = Path(__file__).resolve().parents[1]


class WeddingTests(unittest.TestCase):
    def test_add_remove_has(self):
        with tempfile.TemporaryDirectory() as folder:
            day = date(2026, 10, 17)
            self.assertTrue(wedding.add(folder, day))
            self.assertFalse(wedding.add(folder, day))            # 중복 없음
            self.assertTrue(wedding.has(folder, day))
            self.assertEqual(wedding.load(folder), [day])
            self.assertTrue(wedding.remove(folder, day))
            self.assertFalse(wedding.has(folder, day))

    def test_leave_tab_input_and_calendar_pc_mobile(self):
        from streamlit.testing.v1 import AppTest
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                at = AppTest.from_string(
                    "import streamlit as st\nfrom datetime import date\nimport leave_view_ui\n"
                    f"st.query_params['view']={view!r}\n"
                    "st.session_state.setdefault('leave_month',(2026,10))\nleave_view_ui.page()\n", default_timeout=60)
                with patch("night_shift.order_source.latest_file", return_value=None):
                    at.run()
                    self.assertFalse(at.exception, [e.value for e in at.exception])
                    self.assertTrue(any(e.label.startswith("💒 웨딩 일정") for e in at.expander))
                    at.date_input(key="wedding_day").set_value(date(2026, 10, 17)).run()
                    at.button(key="wedding_add").click().run()
                    self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(wedding.load(folder), [date(2026, 10, 17)])
                shown = " ".join(m.value for m in at.markdown)
                self.assertIn("💒 웨딩", shown)                       # 달력(PC)·날짜 목록(폰)에 표시
                with patch("night_shift.order_source.latest_file", return_value=None):
                    at.button(key="wedding_del_2026-10-17").click().run()
                self.assertEqual(wedding.load(folder), [])

    def test_weekend_notes_mark(self):
        from night_shift.weekend_day import WeekendSchedule
        import weekend_day_ui as ui
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
            names = {"A": "통제A", **{str(i): n for i, n in enumerate(("만년", "원종", "제욱", "광희", "성호", "준호"), 1)}}
            s = WeekendSchedule("2026-10-17", names, {p: ["휴게"] * 10 for p in names})
            self.assertFalse(any("💒" in line for line in ui.weekend_notes(s)))
            wedding.add(folder, date(2026, 10, 17))
            self.assertIn("💒 웨딩 있는 날 (연차일정 탭에서 입력)", ui.weekend_notes(s))


class LastRestSummaryTests(unittest.TestCase):
    def save(self, store, day, resting):
        grid = {p: ["G1"] * 14 for p in ("A", "1", "2", "3", "4", "5", "6")}
        for p in resting:
            grid[p][13] = "휴게"
        record = imp.build_import_record(day, Mode.FM, grid, {p: p for p in grid}, imp.ROSTER)
        history_store.save_confirmed(store, record, "2.20")

    def test_counts_mixing_and_month(self):
        import history_ui
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
            store = Path(folder)
            self.save(store, date(2026, 10, 3), ["1", "2"])
            self.save(store, date(2026, 10, 4), ["2"])            # 2번이 직전에 이어 또 받음
            self.save(store, date(2026, 10, 9), ["3"])
            # 2026-10-13 사용자 요청: 문장 대신 순찰표 같은 표(사람 × 날짜 + 최근 6근무·이번 달 횟수)
            current = history_store.actual_record(store, date(2026, 10, 9))
            html = history_ui.last_rest_table_html(date(2026, 10, 10), current)
            self.assertIn("표에 표시된 수혜 횟수 차이 2회", html)          # 2번 2회, 4·5·6번 0회
            self.assertIn("연속 수혜: 10/04 원종", html)
            for head in ("10/03", "10/04", "10/09", "이번"):
                self.assertIn(f"<th>{head}</th>", html)
            # 2026-10-13 사용자 요청: 받은 칸만 🛌, 점·실선·횟수 열·주석 없음
            self.assertIn("<tr><td class='name'>원종</td><td>🛌</td><td>🛌</td><td></td><td></td></tr>", html)
            for gone in ("·", "—", "최근 6근무</th>", "이번 달</th>", "근무했지만"):
                self.assertNotIn(gone, html.split("</div>", 1)[1])
            self.assertEqual(history_ui.last_rest_table_html(date(2026, 9, 1)), "")   # 기록 없으면 표 없음


class DateLinkTests(unittest.TestCase):
    def test_saved_dates_become_links(self):
        # 2026-10-13 사용자 요청: '앞으로의 편성 방향' 현장 변동 날짜 → 그 근무표로
        import history_ui
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
            LastRestSummaryTests.save(None, Path(folder), date(2026, 10, 9), ["1"])
            html = history_ui.link_night_dates("원종 현장 변동: 10/09 22시~04시 · 10/11 없음 <b>", 2026)
            self.assertIn('href="?night_date=2026-10-09"', html)
            self.assertIn(">10/09</a>", html)
            self.assertNotIn("night_date=2026-10-11", html)          # 저장본 없는 날짜는 글자 그대로
            self.assertIn("&lt;b&gt;", html)                          # 나머지 글자는 이스케이프


if __name__ == "__main__":
    unittest.main()
