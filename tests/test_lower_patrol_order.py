"""14-7 하층 순찰 순번 (2026-10-19 사용자 확정): 마지막 하층 뒤 상층·중층 순찰 출근 3회 이상이면 후보,
마지막 하층이 오래된 사람부터. 이력은 야간 + 공휴일 주간."""
import unittest
from datetime import date

from tests.test_manager_late_half import NAMES, staff
from night_shift import history_import as imp
from night_shift.models import AssignmentKind, Mode
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, run_schedule
from night_shift.soft_history import lower_patrol_wait

DAY = date(2026, 10, 27)
OPTIONS = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)


def event(day, name, *zones, shift=1):
    return {"date": day, "shift": shift, "name": name, "excluded": False, "patrol": bool(zones), "zones": tuple(zones)}


class LowerPatrolWaitTests(unittest.TestCase):
    def test_needs_three_other_floor_shifts_after_last_lower(self):
        events = [event("2026-10-01", "만년", "lower"), event("2026-10-02", "만년", "upper"),
                  event("2026-10-03", "만년", "middle")]
        self.assertIsNone(lower_patrol_wait(events, "만년"))                    # 다른 층 2회
        events.append(event("2026-10-04", "만년", "upper", shift=0))            # 공휴일 주간도 센다
        self.assertEqual(lower_patrol_wait(events, "만년"), "2026-10-01")

    def test_no_patrol_shift_is_not_counted(self):
        events = [event("2026-10-01", "만년", "lower"), event("2026-10-02", "만년", "upper"),
                  event("2026-10-03", "만년"), event("2026-10-04", "만년", "middle")]
        self.assertIsNone(lower_patrol_wait(events, "만년"))

    def test_never_lower_is_oldest_group(self):
        events = [event(f"2026-10-0{i}", "광희", "upper") for i in (1, 2, 3)]
        self.assertEqual(lower_patrol_wait(events, "광희"), "")
        self.assertIsNone(lower_patrol_wait(events[:2], "광희"))


class LowerPatrolSolverTests(unittest.TestCase):
    def test_candidate_gets_lower_patrol(self):
        names = [n[-2:] for n in NAMES.values()]
        target = names[0]
        events = []
        for i, day in enumerate(("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-26")):
            for n in names:
                if n == target:
                    events.append(event(day, n, "upper" if i % 2 else "middle"))
                else:
                    events.append(event(day, n, "lower" if i == 3 else "upper"))   # 다른 사람은 최근 하층 → 후보 아님
        out = run_schedule(ShiftRequest(DAY, imp.night_type_for(DAY), Mode.FM, staff()),
                           HistorySelection(patrol_events=tuple(events)), OPTIONS)
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        pid = next(p for p, n in NAMES.items() if n[-2:] == target)
        self.assertTrue(any(r.employee_id == pid and r.actual_post_or_work_type.kind == AssignmentKind.PATROL
                            and r.actual_post_or_work_type.label == "lower" for r in out.record.assignments))
        self.assertIn("lower_oldest_never", [a.get("stage") for a in out.solve_result.attempts])


if __name__ == "__main__":
    unittest.main()
