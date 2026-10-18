"""2026-10-13: 룰북 8-6(삭제)·15-0 — 통제A는 04시 I1에 배정하지 않는다(8-10 하드). 관리자 04시 I1 선호는 완전 삭제."""
import unittest
from datetime import date

from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode
from night_shift.validator import validate_first_trial


def record(day, a04="I1"):
    grid = {p: ["휴게"] * 14 for p in ("A", "1", "2", "3", "4", "5", "6")}
    grid["A"][10] = a04
    return imp.build_import_record(day, Mode.FM, grid, {p: p for p in grid}, imp.ROSTER)


def errors(rec, **kw):
    return [e for e in validate_first_trial(rec, HistoryInput((), ()), rules_v220=True, **kw)
            if e["rule"] == "8-10" and "I1" in e.get("message", e.get("detail", str(e)))]


class A04I1Tests(unittest.TestCase):
    def test_validator_rejects_a_at_04_i1_old_and_new_barrier_dates(self):
        for day in (date(2026, 10, 3), date(2026, 10, 16)):      # 옛 차단봉 규칙 날짜·단독 담당 날짜 모두
            self.assertTrue(errors(record(day)), day)
            self.assertFalse(errors(record(day, "G1")), day)

    def test_no_soft_preference_report(self):
        from night_shift import analysis
        source = open(analysis.__file__, encoding="utf-8").read()
        self.assertNotIn('add("8-6"', source)                     # 분석 화면 '권장 미충족'에서도 삭제


if __name__ == "__main__":
    unittest.main()
