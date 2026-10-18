"""17-2 포스트 고루 배정 (2026-10-04 사용자 확정)과 생성 때마다 보이는 밸런스 판정."""
import unittest
from datetime import date
from types import SimpleNamespace

from night_shift.balance_notes import balance_verdict
from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(half=None):
    people = [StaffInput("A", "통제", True, False, None, True)]
    for p, n in NAMES.items():
        slots = tuple(range(7)) if p == half else None
        people.append(StaffInput(p, n, True, True, int(p), False, slots))
    return tuple(people)


def counts(record, pid):
    out = {"G1": 0, "L3": 0, "I1": 0}
    for r in record.assignments:
        if r.employee_id == pid and r.displayed_assignment.label in out:
            out[r.displayed_assignment.label] += 1
    return out


class PostCoverageTests(unittest.TestCase):
    def test_full_attendance_everyone_takes_g1_l3_i1(self):
        for night, day, mode in ((NightType.N1, date(2026, 9, 28), Mode.FM),
                                 (NightType.N4, date(2026, 10, 3), Mode.FLEXIBLE)):
            with self.subTest(night=night.value, mode=mode.value):
                result = run_schedule(ShiftRequest(day, night, mode, staff()), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=30))
                self.assertTrue(result.valid)                       # 독립 Validator 0건
                for pid in NAMES:
                    self.assertTrue(all(counts(result.record, pid).values()), (pid, counts(result.record, pid)))
                stages = [a.get("stage") for a in result.solve_result.attempts]
                self.assertLess(stages.index("post_coverage"), stages.index("manager_work"))   # 하드 바로 다음
                self.assertLess(stages.index("general_balance"), stages.index("post_spread"))  # 피로도·실휴게 다음
                text = " ".join(balance_verdict(result.record, result.employee_stats, result.solve_result.attempts))
                self.assertIn("밸런스 판정", text)
                self.assertIn("모두 G1·L3·I1을 1번 이상", text)

    def test_half_day_turns_coverage_off(self):
        result = run_schedule(ShiftRequest(date(2026, 9, 28), NightType.N1, Mode.FM, staff(half="3")),
                              HistorySelection(), SolveOptions(rules_version="2.20", seconds=30))
        self.assertTrue(result.valid)
        self.assertNotIn("post_coverage", [a.get("stage") for a in result.solve_result.attempts])
        text = " ".join(balance_verdict(result.record, result.employee_stats, result.solve_result.attempts))
        self.assertNotIn("포스트 고루 배정", text)


def fake(rows, values):
    """rows: {pid: [label, ...]}, values: {pid: (fatigue, rest)}."""
    stats = {pid: SimpleNamespace(employee_id=pid, is_manager=False, available_time=14, display_number=int(pid),
                                  name=NAMES[pid], fatigue_value=f, actual_rest_time_value=r, patrol_count=1)
             for pid, (f, r) in values.items()}
    assignments = [SimpleNamespace(employee_id=pid, displayed_assignment=SimpleNamespace(label=label),
                                   barrier_install_flag=False, barrier_remove_flag=False)
                   for pid, labels in rows.items() for label in labels]
    context = SimpleNamespace(attendance=(), partial_vacancy_profile=None, flexible_from_slot=None,
                              night_type=NightType.N4, manager_handover=None)
    return SimpleNamespace(context=context, assignments=assignments), stats


class VerdictTests(unittest.TestCase):
    def test_perfect_split_and_integer_remainder(self):
        rows = {p: ["G1", "L3", "I1"] + ["휴게"] * 11 for p in ("1", "2", "3")}
        record, stats = fake(rows, {"1": (12, 6), "2": (12, 6), "3": (12, 6)})
        self.assertIn("완전 n빵", balance_verdict(record, stats)[0])
        record, stats = fake(rows, {"1": (12, 6), "2": (12, 6), "3": (13, 6)})
        text = " ".join(balance_verdict(record, stats))
        self.assertIn("합계 37점을 3명이 나누면 1점이 남아", text)

    def test_missing_post_and_timeout_are_reported(self):
        rows = {"1": ["G1", "L3", "I1"] + ["휴게"] * 11, "2": ["G1", "G1", "I1"] + ["휴게"] * 11}
        record, stats = fake(rows, {"1": (10, 6), "2": (13, 6)})
        attempts = [{"stage": "post_coverage", "status": "OPTIMAL"}, {"stage": "general_balance", "status": "FEASIBLE"}]
        text = " ".join(balance_verdict(record, stats, attempts))
        self.assertIn("한 번도 안 선 포스트 — 2 원종 L3", text)
        self.assertIn("다른 하드룰 때문에", text)
        self.assertIn("제한시간을 늘려", text)                   # 차이 3점 > 정수 한계 → 시간 부족 안내
        self.assertIn("밸런스보다 먼저 지키는 규칙", text)


if __name__ == "__main__":
    unittest.main()
