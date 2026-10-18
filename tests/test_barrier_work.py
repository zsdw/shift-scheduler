"""룰북 11-0 (2026-10-04 사용자 확정): 실근무는 포스트·순찰만. 차단봉만 한 칸은 피로도 1·실근무 0·실휴게 0."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from night_shift import history_store
from night_shift.models import AssignmentKind, HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def generate():
    staff = [StaffInput("A", "통제", True, False, None, True)]
    staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
    result = run_schedule(ShiftRequest(date(2026, 10, 3), NightType.N4, Mode.FM, tuple(staff)), HistorySelection(),
                          SolveOptions(rules_version="2.20", seconds=20))
    assert result.valid
    return result


class BarrierWorkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = generate()
        cls.barrier = [r for r in cls.result.record.assignments
                       if r.actual_post_or_work_type.kind == AssignmentKind.BARRIER_ONLY]

    def test_barrier_only_cells_are_fatigue_one_no_work_no_rest(self):
        self.assertEqual(len(self.barrier), 2)                        # FM 20시 설치·04시 철수
        for r in self.barrier:
            self.assertEqual((r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value), (1, 0, 0))
        stats = calculate_all_stats(self.result.record)
        for pid in NAMES:
            rows = [r for r in self.result.record.assignments if r.employee_id == pid]
            posts_and_patrols = sum(r.actual_work_time_value for r in rows
                                    if r.actual_post_or_work_type.kind in (AssignmentKind.POST, AssignmentKind.PATROL))
            self.assertEqual(stats[pid].actual_work_time_value, posts_and_patrols)

    def test_validator_rejects_old_barrier_work_hour(self):
        old = self.barrier[0]
        rows = tuple(replace(r, actual_work_time_value=1) if r is old else r for r in self.result.record.assignments)
        errors = validate_first_trial(replace(self.result.record, assignments=rows), HistoryInput((), ()),
                                      rules_v220=True)
        self.assertTrue(any("Accounting" in e["detail"] for e in errors), errors)

    def test_old_saved_file_is_recomputed_on_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = history_store.save_confirmed(Path(folder), self.result.record, "2.20")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for r in data["plan"]["assignments"]:                      # 예전 기준으로 저장된 파일 흉내
                if r["actual"][0] == AssignmentKind.BARRIER_ONLY.value:
                    r["work"] = 1
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            actual = history_store.actual_record(Path(folder), date(2026, 10, 3))
            self.assertTrue(all(r.actual_work_time_value == 0 for r in actual.assignments
                                if r.actual_post_or_work_type.kind == AssignmentKind.BARRIER_ONLY))
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8"))["plan"]["assignments"]
                             [0].keys(), data["plan"]["assignments"][0].keys())   # 파일은 그대로


if __name__ == "__main__":
    unittest.main()
