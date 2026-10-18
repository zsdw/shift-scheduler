import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from night_shift import leave_schedule as ls, daily_report as dr

DAY = date(2026, 10, 8)


class ManualLeaveTests(unittest.TestCase):
    def test_refresh_existing_input_after_registration_and_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            for mode, key in (("day", f"day_statuses_{DAY}"), ("night", "night_status_date"), ("weekend", f"wd_statuses_{DAY}")):
                state = {key: "old"}
                self.assertFalse(ls.refresh_manual_inputs(state, store, DAY, mode))
                eid = ls.save_manual(store, "김광희", "A", DAY, DAY, "연차")
                self.assertTrue(ls.refresh_manual_inputs(state, store, DAY, mode))
                self.assertNotIn(key, state)
                state[key] = "manual choice"
                self.assertFalse(ls.refresh_manual_inputs(state, store, DAY, mode))
                self.assertIn(key, state)
                ls.delete_manual(store, eid)
                self.assertTrue(ls.refresh_manual_inputs(state, store, DAY, mode))
                self.assertNotIn(key, state)

    def test_override_upload_edit_delete_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            ls.save_text(store, "10월 8일\nA조 김광희 사원 - 연차")
            original = (store / ls.LEAVE_FILE).read_bytes()
            eid = ls.save_manual(store, "김광희", "A", DAY, date(2026, 10, 9), "교육", "직무교육")
            self.assertEqual(ls.load(store)[DAY][0]["kind"], "교육")
            self.assertEqual(ls.load(store)[date(2026, 10, 9)][0]["note"], "직무교육")
            self.assertEqual((store / ls.LEAVE_FILE).read_bytes(), original)
            ls.save_text(store, "10월 8일\nA조 김광희 사원 - 휴무")
            self.assertEqual(ls.load(store)[DAY][0]["kind"], "교육")
            ls.save_manual(store, "김광희", "A", DAY, DAY, "연차", item_id=eid)
            self.assertNotIn(date(2026, 10, 9), ls.load(store))
            ls.delete_manual(store, eid)
            self.assertEqual(ls.load(store)[DAY][0]["kind"], "휴무")
            self.assertTrue(list((store / ".trash").glob("manual_leave_*.json")))

    def test_overlap_invalid_and_cross_year(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            ls.save_manual(store, "김광희", "A", date(2026, 12, 31), date(2027, 1, 2), "연차")
            self.assertIn(date(2027, 1, 2), ls.load(store, 2027))
            with self.assertRaises(ValueError):
                ls.save_manual(store, "김광희", "A", date(2027, 1, 1), date(2027, 1, 3), "교육")
            with self.assertRaises(ValueError):
                ls.save_manual(store, "김광희", "A", date(2027, 2, 2), date(2027, 2, 1), "연차")

    def test_presence_and_support(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            eid = ls.save_manual(store, "김광희", "A", DAY, DAY, "기타", "개인 일정", "미출근")
            entries = ls.load(store)
            self.assertEqual(ls.defaults_for(entries, DAY, "day", ["광희"])[0]["광희"][0], "기타")
            report = dr.build(DAY, dr.entries_for(store, DAY), dr.load_roster(store))
            row = next(r for r in report["rows"] if r.get("조") == "A조")
            self.assertIn("미출근:기타 · 개인 일정", row["비고"])
            from night_shift.security_order import present
            self.assertFalse(present("김광희", report["rows"]))
            ls.save_manual(store, "김광희", "A", DAY, DAY, "야간지원", item_id=eid)
            entries = ls.load(store)
            self.assertEqual(ls.defaults_for(entries, DAY, "day", ["광희"])[0]["광희"][0], "기타")
            self.assertEqual(ls.defaults_for(entries, DAY, "night", ["광희"])[0]["광희"][0], "출근")

    def test_saved_schedule_preserved_and_difference_shown(self):
        from night_shift.day_shift import DayPerson, DaySchedule, save_day
        from night_shift.date_check import review
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            schedule = DaySchedule(DAY, (DayPerson("광희", "광희", "출근", 1),), {"광희": ["휴게"] * 10})
            save_day(store / "day", schedule)
            path = store / "day" / f"{DAY}.json"
            original = path.read_bytes()
            ls.save_manual(store, "김광희", "A", DAY, DAY, "연차")
            issues = review(store, DAY, {})
            self.assertTrue(any(i["kind"] == "absent_listed" and i["person"] == "김광희" for i in issues))
            self.assertEqual(path.read_bytes(), original)

    def test_explicit_presence_on_rest_day_and_note_parsing(self):
        from night_shift.security_order import present
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            ls.save_manual(store, "최찬우", "D", date(2026, 10, 9), date(2026, 10, 9), "기타", "교육(외부), 참석", "출근")
            report = dr.build(date(2026, 10, 9), dr.entries_for(store, date(2026, 10, 9)), dr.load_roster(store))
            self.assertTrue(present("최찬우", report["rows"], off=True))
            row = next(r for r in report["rows"] if r["구분"] == "주간고정")
            self.assertEqual(row["사고"], dr.TO["주간고정"] - 1)

    def test_ui_pc_mobile_register_edit_delete(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False, True):
            with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                at = AppTest.from_string(f"import leave_view_ui as ui\nfrom pathlib import Path\nimport streamlit as st\nst.query_params['view'] = {'mobile' if mobile else 'pc'!r}\nui.manual_box(Path({folder!r}))")
                at.run()
                self.assertFalse(at.exception)
                at.button[0].click().run()
                self.assertFalse(at.exception)
                self.assertEqual(len(ls.load_manual(Path(folder))), 1)
                eid = ls.load_manual(Path(folder))[0]["id"]
                at.selectbox[0].select(eid).run()
                at.text_input[0].input("수정 비고")
                at.button[0].click().run()
                self.assertEqual(ls.load_manual(Path(folder))[0]["note"], "수정 비고")
                next(b for b in at.button if "삭제" in b.label).click().run()
                self.assertFalse(at.exception)
                self.assertEqual(ls.load_manual(Path(folder)), [])

    def test_weekend_roster_pc_mobile(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False, True):
            with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                ls.save_manual(Path(folder), "김광희", "A", DAY, DAY, "연차")
                at = AppTest.from_string(f"from datetime import date\nimport weekend_day_ui as ui\nui._roster_input(date(2026,10,8), {mobile})")
                at.run()
                self.assertFalse(at.exception, [e.message for e in at.exception])
                self.assertTrue(any("광희 연차" in c.value for c in at.caption))
