"""H-22 [하드, 2026-10-22 사용자 확정]: 결원 0~1명(통제 결근 포함) 날 누구든(통제A·준호 포함) 4시간 연속 근무 금지,
실제 운영 기준(실근무 = 근무, 유도리 휴게성 포스트·휴게·업무 없는 대기·차단봉만 = 쉼). 네 칸 모두 LOCK이면 보존."""
import unittest
from dataclasses import replace

from night_shift.models import AssignmentKind as K, HistoryInput, Mode, NightType
from night_shift.profiles import make_record
from night_shift.service import HistorySelection, ShiftRequest, run_schedule
from night_shift.validator import validate_first_trial
from tests.test_proxy_lowest import DAY, OPTIONS, staff


def fm_runs(record):
    work = {(r.employee_id, r.slot.index) for r in record.assignments if r.actual_work_time_value == 1}
    people = {r.employee_id for r in record.assignments}
    return [(p, s) for p in people for s in range(11) if all((p, t) in work for t in range(s, s + 4))]


class FourRunHardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {
            "FM 결원0": run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff()), HistorySelection(), OPTIONS),
            "유도리 통제결근": run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FLEXIBLE, staff(a_present=False)),
                                      HistorySelection(), OPTIONS),
            "FM 결원1": run_schedule(ShiftRequest(DAY, NightType.N3, Mode.FM, staff(absent=("2",))),
                                    HistorySelection(), OPTIONS),
        }

    def test_generated_tables_have_no_fm_four_hour_run(self):
        for name, result in self.results.items():
            with self.subTest(name):
                self.assertTrue(result.valid, result.validation_errors)
                self.assertEqual(fm_runs(result.record), [])

    def bad(self):
        rec = self.results["FM 결원0"].record
        cells = {5: "휴게", 6: "G1", 7: "L3", 8: "G1", 9: "L3", 10: "휴게"}
        rows = [make_record(rec.context, "1", r.slot.index, cells[r.slot.index], patrol_standing=True)
                if r.employee_id == "1" and r.slot.index in cells else r for r in rec.assignments]
        return replace(rec, assignments=tuple(rows))

    def test_validator_rejects_four_hour_run(self):
        errors = validate_first_trial(self.bad(), HistoryInput((), ()), rules_v220=True)
        self.assertTrue(any(e["rule"] == "H-22" for e in errors))

    def test_fully_locked_run_is_kept(self):
        errors = validate_first_trial(self.bad(), HistoryInput((), ()), rules_v220=True,
                                      locked_cells=tuple(("1", t) for t in (6, 7, 8, 9)))
        self.assertFalse(any(e["rule"] == "H-22" for e in errors))


if __name__ == "__main__":
    unittest.main()
