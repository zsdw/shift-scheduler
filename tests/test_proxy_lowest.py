"""2026-10-20 사용자 확정: 하루 종일 준호 대행(A 결근)은 준호 피로도 = 일반근무자 중 최저(하드, 결원 0·1·2 공통 — 10/22부터 각 일반근무자보다 1~2점 낮게),
결원 2명 날 통제A 하대 금지(통제A ≤ 일반근무자 최고, 하드), 대행 날 2회 순찰 관리자 선호 없음, 장부에 대행 준호 적립."""
import unittest
from dataclasses import replace
from datetime import date, datetime

from night_shift import fatigue_ledger as ledger
from night_shift.models import HistoryInput, Mode, NightType, RecordKind
from night_shift.profiles import make_record
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

    # 2026-10-22 사용자 확정: 하루 종일 대행 준호 = 각 일반근무자보다 1~2점 낮게(동점 금지)
    def test_full_day_proxy_is_lowest_with_two_vacancies(self):
        r = self.vac2
        self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
        self.assertTrue(all(1 <= g - fatigue(r)["6"] <= 2 for g in self.general_fatigue(r, ("2", "6"))), fatigue(r))

    def test_full_day_proxy_is_lowest_without_vacancy(self):
        r = self.vac0
        self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
        self.assertTrue(all(1 <= g - fatigue(r)["6"] <= 2 for g in self.general_fatigue(r, ("6",))), fatigue(r))

    def test_full_day_proxy_rest_around_patrol_at_most_two(self):
        # 2026-10-22 사용자 확정: 대행 준호(결원 1명까지)는 순찰 앞 2시간 + 뒤 2시간 중 휴게 최대 2시간
        from night_shift.models import AssignmentKind
        rows = {r.slot.index: r for r in self.vac0.record.assignments if r.employee_id == "6"}
        patrols = [t for t, r in rows.items() if r.actual_post_or_work_type.kind == AssignmentKind.PATROL]
        self.assertTrue(patrols)
        for t in patrols:
            window = [j for j in (t - 2, t - 1, t + 1, t + 2) if 0 <= j < 14]
            self.assertLessEqual(sum(rows[j].actual_rest_time_value for j in window), 2, (t, window))
        # 위반표 거부: 순찰 앞뒤를 모두 휴게로 바꾼 표
        from night_shift.profiles import make_record
        t = patrols[0]
        window = [j for j in (t - 2, t - 1, t + 1, t + 2) if 0 <= j < 14]
        bad = replace(self.vac0.record, assignments=tuple(
            make_record(self.vac0.record.context, "6", r.slot.index, "휴게")
            if r.employee_id == "6" and r.slot.index in window else r for r in self.vac0.record.assignments))
        self.assertIn("대행준호-순찰앞뒤휴게", rules(bad))

    def test_full_day_proxy_takes_no_barrier_duty(self):
        # 2026-10-22 사용자 지적: 대행 준호는 관리자 — 차단봉 설치·철수 불참(04시 I1 = 철수라 04시 I1도 불가)
        from night_shift.actual_edit import apply_edits
        for r in (self.vac0, self.vac2):
            duty = [x for x in r.record.assignments if x.employee_id == "6" and (x.barrier_install_flag or x.barrier_remove_flag)]
            self.assertEqual(duty, [])
        i1 = next(x.employee_id for x in self.vac0.record.assignments if x.slot.index == 10 and x.displayed_assignment.label == "I1")
        bad = apply_edits(self.vac0.record, [{"type": "swap", "a": ["6", 10], "b": [i1, 10]}])
        self.assertTrue(any(x.employee_id == "6" and x.barrier_remove_flag for x in bad.assignments))
        self.assertIn("15-0-대행", rules(bad))

    def test_full_day_proxy_04_i1_and_03_i1_goal_order(self):
        # 2026-10-22 사용자 확정: 04시 비우기 … 대폭 휴게 뒤에 03시 I1 (03시 비우기·04시 I1은 삭제)
        stages = [a.get("stage") for a in self.vac0.solve_result.attempts if isinstance(a, dict)]
        self.assertNotIn("proxy_03_rest", stages)
        self.assertNotIn("proxy_04_i1", stages)                    # 04시 I1은 차단봉 철수라 대행 불가(삭제)
        big = [i for i, s in enumerate(stages) if str(s).startswith("big_rest_")]
        if big:
            self.assertGreater(stages.index("proxy_03_i1"), max(big))

    def test_validator_rejects_proxy_above_lowest(self):
        r = self.vac2
        f = fatigue(r)
        top = max((p for p in NAMES if p not in ("2", "6")), key=lambda p: f[p])
        # 맞바꾸기만 하면 차이 1점 표에서 검증기 재계산 기준 동점(허용)이 될 수 있어, 준호 휴게 1칸을 G2로 바꿔 확실히 최저 초과로 만든다
        bad = swap_rows(r.record, "6", top)
        rows = list(bad.assignments)
        i = next(i for i, a in enumerate(rows)
                 if a.employee_id == "6" and 1 <= a.slot.index <= 12 and a.actual_post_or_work_type.label == "휴게")
        rows[i] = make_record(bad.context, "6", rows[i].slot.index, "G2")
        self.assertIn("대행준호-최저피로도", rules(replace(bad, assignments=tuple(rows))))
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
