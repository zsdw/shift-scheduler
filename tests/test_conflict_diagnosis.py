"""해 없음 원인 자동 진단 (2026-10-18 사용자 요청): 어떤 하드 규칙 묶음이 막는지 찾는다. 실제 규칙은 풀지 않는다."""
import re
import unittest
from pathlib import Path

from tests.test_manager_late_half import request
from night_shift.service import (HistorySelection, RULE_GROUPS, SolveOptions, find_conflicting_rules, run_schedule)


class ConflictDiagnosisTests(unittest.TestCase):
    def test_group_names_match_solver(self):
        source = (Path(__file__).resolve().parents[1] / "night_shift" / "solver.py").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'rule_off\("([^"]+)"\)', source)), set(RULE_GROUPS))

    def test_finds_single_blocking_group(self):
        # 일반근무자 1명을 06·07시 모두 쉬게 강제하면 H-20(막타임 2시간 연속 휴게 금지)만 막는다.
        # (10/20 전에는 05·06·07시 강제 → H-19 단독이었으나, 이제 H-19·H-20 둘 다 막아 단독 원인이 없다)
        options = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False,
                               forced_rest_cells=(("1", 12), ("1", 13)))
        self.assertEqual(run_schedule(request(), HistorySelection(), options).solve_result.status, "INFEASIBLE")
        found = find_conflicting_rules(lambda opts: run_schedule(request(), HistorySelection(), opts), options)
        self.assertEqual(found["single"], ["H-20 06·07시 휴게 2연속 금지"])

    def test_feasibility_only_returns_no_table(self):
        out = run_schedule(request(), HistorySelection(),
                           SolveOptions(rules_version="2.20", seconds=10, prefer_dual_mode=False, feasibility_only=True))
        self.assertEqual(out.solve_result.status, "FEASIBLE")
        self.assertIsNone(out.record)


if __name__ == "__main__":
    unittest.main()
