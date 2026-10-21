"""8-10-1 (2026-10-20 사용자 확정, 아주 강한 권장): 관리자(통제A·준호 대행) 04시는 최대한 비운다.

빠진 근무는 그 이전(00~03시)으로, 05·06시 관리자 실근무는 그다음으로 최소화. 가능하면 지킬 규칙 바로 다음,
막타임 순번보다 앞. A 피로도는 8-4-2 하드(일반근무자보다 0~3점 낮거나 같음) 안에서만 움직인다.
"""
import unittest

from night_shift.models import NightType, Mode
from night_shift.service import HistorySelection, ShiftRequest, run_schedule
from tests.test_proxy_lowest import DAY, OPTIONS, staff


def work_at(result, pid, slot):
    return next(r.actual_work_time_value for r in result.record.assignments
                if r.employee_id == pid and r.slot.index == slot)


class Manager0400RestTests(unittest.TestCase):
    def test_manager_and_proxy_04_empty(self):
        for night, a_present, manager in ((NightType.N1, True, "A"), (NightType.N4, True, "A"),
                                          (NightType.N1, False, "6"), (NightType.N4, False, "6")):
            result = run_schedule(ShiftRequest(DAY, night, Mode.FM, staff(a_present=a_present)), HistorySelection(), OPTIONS)
            self.assertIsNotNone(result.record, (night, manager))
            if a_present:       # 7명 온전 출근(결원 0명): 8-10-2 하드 (2026-10-22)
                self.assertEqual(work_at(result, manager, 10), 0, (night, manager))
            # 통제 결근(6명, 결원 1명) 날은 8-10-1 아주 강한 권장 — 6명이면 H-11과 겹쳐 비우지 못하는 날이 있다(10/22 사용자 확정)
            stages = [a.get("stage") for a in result.solve_result.attempts if isinstance(a, dict)]
            self.assertLess(stages.index("manager_04_rest"),
                            min([stages.index(s) for s in stages if s and s.startswith("last_rest_oldest_")] or [99]))

    def test_manager_fatigue_stays_within_hard_gap(self):
        result = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff()), HistorySelection(), OPTIONS)
        fatigue = {p: s.fatigue_value for p, s in result.employee_stats.items()}
        generals = [v for p, v in fatigue.items() if p != "A"]
        self.assertTrue(all(0 <= g - fatigue["A"] <= 3 for g in generals), fatigue)


if __name__ == "__main__":
    unittest.main()
