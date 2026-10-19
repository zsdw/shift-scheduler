"""2026-10-20 사용자 확정: 하루 종일 준호 대행(A 결근)은 준호 피로도 = 일반근무자 중 최저(하드, 결원 0·1·2 공통),
결원 2명 날 통제A 하대 금지(통제A ≤ 일반근무자 최고, 하드), 대행 날 2회 순찰 관리자 선호 없음, 장부에 대행 준호 적립."""
import unittest
from dataclasses import replace
from datetime import date, datetime

from night_shift import fatigue_ledger as ledger
from night_shift.models import HistoryInput, Mode, NightType, RecordKind
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
OPTIONS = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
DAY = date(2026, 10, 27)


def staff(absent=(), a_present=True):
    rows = [StaffInput("A", "통제", a_present, False, None, True)]
    for p, n in NAMES.items():
        proxy = p == "6" and not a_present
        rows.append(StaffInput(p, n, p not in absent, not proxy, int(p), proxy))
    return tuple(rows)


def fatigue(result):
    return {p: s.fatigue_value for p, s in result.employee_stats.items()}


def swap_rows(record, a, b):
    rows = [replace(r, employee_id=b if r.employee_id == a else a if r.employee_id == b else r.employee_id)
            for r in record.assignments]
    return replace(record, assignments=tuple(rows))


def rules(record):
    return {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)}


class ProxyLowestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vac2 = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(absent=("2",), a_present=False)),
                                HistorySelection(), OPTIONS)
        cls.vac0 = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(a_present=False)),
                                HistorySelection(), OPTIONS)
        cls.a_vac2 = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(absent=("2", "3"))),
                                  HistorySelection(), OPTIONS)

    def general_fatigue(self, result, exclude):
        f = fatigue(result)
        return [f[p] for p in NAMES if p not in exclude and p in f]

    def test_full_day_proxy_is_lowest_with_two_vacancies(self):
        r = self.vac2
        self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
        self.assertLessEqual(fatigue(r)["6"], min(self.general_fatigue(r, ("2", "6"))))

    def test_full_day_proxy_is_lowest_without_vacancy(self):
        r = self.vac0
        self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
        self.assertLessEqual(fatigue(r)["6"], min(self.general_fatigue(r, ("6",))))

    def test_validator_rejects_proxy_above_lowest(self):
        r = self.vac2
        f = fatigue(r)
        top = max((p for p in NAMES if p not in ("2", "6")), key=lambda p: f[p])
        if f[top] > f["6"]:
            self.assertIn("대행준호-최저피로도", rules(swap_rows(r.record, "6", top)))
        self.assertNotIn("대행준호-최저피로도", rules(r.record))

    def test_vacancy_day_manager_not_above_every_general(self):
        r = self.a_vac2
        self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
        f = fatigue(r)
        self.assertLessEqual(f["A"], max(f[p] for p in ("1", "4", "5", "6")))
        self.assertNotIn("관리자-하대금지", rules(r.record))

    def test_ledger_records_full_day_proxy_against_general_average(self):
        record = replace(self.vac2.record, kind=RecordKind.ACTUAL, confirmed_at=datetime(2026, 10, 28, 8))
        values, extras = ledger.night_values(record), ledger.night_extras(record)
        self.assertNotIn("준호", values)
        self.assertIn("준호", extras)
        delta = ledger.day_delta(values, extras)
        average = sum(values.values()) / len(values)
        self.assertAlmostEqual(float(delta["준호"]), extras["준호"] - average)
        self.assertAlmostEqual(float(sum(delta[n] for n in values)), 0.0)
        balances, _ = ledger.night_from_records([record], date(2026, 10, 28))
        self.assertIn("준호", balances)


if __name__ == "__main__":
    unittest.main()
