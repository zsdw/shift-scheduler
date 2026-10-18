"""LOCK만 고른 재생성 (2026-10-18 사용자 요청): 빠지는 사람 없이 LOCK까지 그대로, 남은 시간만 다른 후보."""
import unittest
from dataclasses import replace

from tests.test_manager_late_half import request
from night_shift.service import (HistorySelection, SolveOptions, run_lock_regeneration, run_schedule,
                                 run_schedule_manager_half, revalidate)

OPTIONS = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)


def payload(result):
    return tuple({"employee_id": r.employee_id, "slot": {"index": r.slot.index},
                  "displayed_assignment": {"kind": r.displayed_assignment.kind.value, "label": r.displayed_assignment.label},
                  "actual_post_or_work_type": {"kind": r.actual_post_or_work_type.kind.value,
                                               "label": r.actual_post_or_work_type.label},
                  "barrier_install_flag": r.barrier_install_flag, "barrier_remove_flag": r.barrier_remove_flag}
                 for r in result.record.assignments)


class LockRegenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = run_schedule(request(), HistorySelection(), OPTIONS)

    def test_prefix_kept_and_suffix_differs(self):
        self.assertTrue(self.base.valid, self.base.validation_errors)
        start = 6                                                   # 23시까지 LOCK, 00시부터 다시
        out = run_lock_regeneration(self.base, start, HistorySelection(), OPTIONS, exclude=(payload(self.base),))
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        self.assertIsNone(out.rebalance_info)                       # 긴급 재편성 아님(빠지는 사람 없음)
        key = lambda r: (r.employee_id, r.slot.index)
        before = {key(r): r for r in self.base.record.assignments}
        after = {key(r): r for r in out.record.assignments}
        for k, row in before.items():
            if k[1] < start:
                self.assertEqual(after[k].displayed_assignment, row.displayed_assignment, k)
        self.assertNotEqual([after[k] for k in sorted(after) if k[1] >= start],
                            [before[k] for k in sorted(before) if k[1] >= start])
        self.assertTrue(revalidate(out, out.record).valid)          # 저장 후 다시 열어도 일반 규칙 통과

    def test_handover_table_rejected(self):
        half = run_schedule_manager_half(request(), HistorySelection(), OPTIONS)
        with self.assertRaises(ValueError):
            run_lock_regeneration(half, 6, HistorySelection(), OPTIONS)


if __name__ == "__main__":
    unittest.main()
