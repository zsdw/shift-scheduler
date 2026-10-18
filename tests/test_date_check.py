"""날짜별 문서 대조 배너 (2026-10-07): 연차일정·근태일보·근무표·명령서 어긋남을 맨 위에 표시 (PC·폰)."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from night_shift import daily_report as dr
from night_shift import date_check
from night_shift.day_shift import DayPerson, DaySchedule, save_day
from night_shift.leave_schedule import save_text

DAY = date(2026, 10, 8)          # A조 주간 · B조 야간 · C조 휴무
WORKERS = ("한만년", "김광희", "김제욱", "유원종", "이준호", "김도운", "조용주", "홍성욱", "윤여진")


def day_schedule(names, leave=()):
    people = tuple(DayPerson(n[-2:], n[-2:], "연차" if n in leave else "출근", None if n in leave else i + 1)
                   for i, n in enumerate(names))
    return DaySchedule(DAY, people, {p.pid: ["휴게"] * 10 for p in people if p.number})


class DateCheckTests(unittest.TestCase):
    def test_consistent_then_mismatches(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\nD조 이준형 사원 - 연차\n")
            save_day(store / "day", day_schedule(WORKERS))
            self.assertFalse([i for i in date_check.check(store, DAY) if i[0] == "error"])
            # 근무표에 연차자가 들어가 있고, 출근자가 빠진 경우
            save_day(store / "day", day_schedule(WORKERS[:-1] + ("이성호",)))
            text = " ".join(m for _, _, m in date_check.check(store, DAY))
            self.assertIn("이성호이(가) 있는데 근태일보상 연차", text)
            self.assertIn("윤여진이(가) 주간 근무표에 없습니다", text)

    @patch("night_shift.order_source.document_available", return_value=True)   # 2026-10-11: 자료 있는 날만 대조
    def test_leave_changed_after_report_saved_and_order_source(self, _available):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\n")
            report = dr.build(DAY, dr.entries_for(store, DAY), dr.load_roster(store))
            dr.save_report(store, DAY, report["rows"], "김현", report["rows"])
            save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\nA조 김광희 사원 - 연차\n")
            source = {"day": {"names": {"1": "만년", "6": "만년"}, "controls": ["E"], "cp": {}, "cells": {}}}
            issues = date_check.check(store, DAY, source)
            where = {w for _, w, _ in issues}
            self.assertFalse(any("일보 저장 뒤" in m for _, _, m in issues))
            self.assertTrue(any("1·6번 이름이 모두 '만년'" in m for _, _, m in issues))

    def test_banner_on_every_tab_pc_and_mobile(self):
        from streamlit.testing.v1 import AppTest
        root = Path(__file__).resolve().parents[1]
        for view in ("pc", "mobile"):
            for tab in ("🗓 근무표", "📋 근태관리 일보", "📝 보안근무명령서", "📅 연차일정"):
                with self.subTest(view=view, tab=tab), tempfile.TemporaryDirectory() as folder, \
                        patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                    store = Path(folder)
                    save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\n")
                    save_day(store / "day", day_schedule(WORKERS[:-1] + ("이성호",)))
                    at = AppTest.from_file(str(root / "app.py"), default_timeout=120)
                    at.query_params["view"] = view
                    at.session_state["app_tab"] = tab
                    at.session_state["shift_date"] = DAY
                    at.session_state["daily_report_day"] = DAY
                    at.session_state["order_day"] = DAY
                    at.session_state["leave_check_day"] = DAY
                    with patch("night_shift.order_source.latest_file", return_value=None):
                        at.run()
                    self.assertFalse(at.exception, [e.value for e in at.exception])
                    shown = " ".join(m.value for m in at.markdown)
                    # 2026-10-10: 차이가 있으면 맨 위 경고 + 연차일정/근무표 기준 선택(document_basis)
                    self.assertTrue(any("10/08 근무표와 연차일정이 다릅니다" in w.value for w in at.warning))
                    self.assertIn("근무표(주간)", shown)
                    self.assertIn("이성호이(가) 있는데 근태일보상 연차", shown)


if __name__ == "__main__":
    unittest.main()


class ResolutionTests(unittest.TestCase):
    def test_fix_report_status_ack_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\n")
            report = dr.build(DAY, dr.entries_for(store, DAY), dr.load_roster(store))
            dr.save_report(store, DAY, report["rows"], "김현", report["rows"])
            save_day(store / "day", day_schedule(WORKERS[:-1]))          # 근무표에 윤여진 없음
            issue = next(i for i in date_check.review(store, DAY) if i["kind"] == "missing" and i["person"] == "윤여진")
            self.assertEqual(issue["level"], "error")
            self.assertEqual(issue["default"], "ack")    # 2026-10-10: 기본은 '연차일정이 맞음'(일보 고치기는 선택)
            message = date_check.apply(store, DAY, issue, "fix", "휴무")
            self.assertIn("윤여진", message)
            row = next(r for r in dr.build(DAY, dr.entries_for(store, DAY), dr.load_roster(store))["rows"] if r["구분"] == "주간고정")
            self.assertIn("휴무 1명(윤여진)", row["비고"])
            self.assertFalse((store / "daily_reports" / ".trash").exists())   # 자동 계산은 과거 저장본을 바꾸지 않음
            self.assertFalse([i for i in date_check.review(store, DAY) if i["kind"] == "missing" and i["person"] == "윤여진"])
            self.assertIn("이성호 사원 - 연차", (store / "leave_schedule.txt").read_text(encoding="utf-8"))  # 원본 그대로
            # 편성표 엑셀 쪽 차이 → 확인함 → 되돌리기 (2026-10-10부터 '자동 판단' 단계 없이 일반 대조 건)
            source = {"night": {"names": {"1": "나현"}, "controls": [], "cp": {}, "cells": {}}}
            auto = next(i for i in date_check.review(store, DAY, source) if i["where"] == "근무명령서")
            date_check.apply(store, DAY, auto, "ack")
            self.assertTrue(next(i for i in date_check.review(store, DAY, source) if i["key"] == auto["key"])["resolved"])
            date_check.unresolve(store, DAY, auto["key"])
            self.assertFalse(next(i for i in date_check.review(store, DAY, source) if i["key"] == auto["key"])["resolved"])

    def test_banner_controls_apply_pc_and_mobile(self):
        from streamlit.testing.v1 import AppTest
        root = Path(__file__).resolve().parents[1]
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                store = Path(folder)
                save_text(store, "10월 08일(목)\nA조 이성호 사원 - 연차\n")
                save_day(store / "day", day_schedule(WORKERS[:-1]))
                at = AppTest.from_file(str(root / "app.py"), default_timeout=120)
                at.query_params["view"] = view
                at.session_state["app_tab"] = "📋 근태관리 일보"
                at.session_state["daily_report_day"] = DAY
                # 2026-10-10: 건별 '적용' 대신 연차일정/근무표 작성 기준 선택 → 저장 → 기준 표시·다시 선택
                with patch("night_shift.order_source.latest_file", return_value=None):
                    at.run()
                    self.assertFalse(at.exception, [e.value for e in at.exception])
                    pick = next(r for r in at.radio if r.label == "작성 기준")
                    pick.set_value("leave").run()
                    next(b for b in at.button if b.label == "선택한 기준으로 작성").click().run()
                    self.assertFalse(at.exception, [e.value for e in at.exception])
                    self.assertTrue(any("문서 작성 기준: 연차일정표" in c.value for c in at.caption))
                    self.assertTrue(any(b.label == "작성 기준 다시 선택" for b in at.button))
