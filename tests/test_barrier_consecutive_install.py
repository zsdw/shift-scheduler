"""15-3 연속 회차 설치 금지 (2026-10-19 사용자 확정): 직전 회차 설치자는 G2·I1 설치든 이번 회차 설치 불가."""
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta

from tests.test_manager_late_half import staff
from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode, RecordKind
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, run_schedule
from night_shift.validator import validate_first_trial

DAY = date(2026, 10, 27)
OPTIONS = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)


def request(day=DAY):
    return ShiftRequest(day, imp.night_type_for(day), Mode.FM, staff())


def as_previous_night(record):
    """같은 표를 하루 전 실제 근무로 바꿔 직전 회차 기록으로 쓴다."""
    context = replace(record.context, shift_start_date=record.context.shift_start_date - timedelta(days=1))
    return replace(record, context=context, kind=RecordKind.ACTUAL, confirmed_at=datetime(2026, 10, 26, 8))


def installers(record):
    return {r.employee_id for r in record.assignments if r.barrier_install_flag}


def duty_people(record):
    return {r.employee_id for r in record.assignments if r.barrier_install_flag or r.barrier_remove_flag}


def rules(record, previous, locked=()):
    return {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True,
                                                    last_rest_records=previous, locked_cells=locked)}


class ConsecutiveInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = run_schedule(request(), HistorySelection(), OPTIONS)
        cls.previous = as_previous_night(cls.base.record)

    def test_base_has_single_post_installer(self):
        self.assertTrue(self.base.valid, self.base.validation_errors)
        rows = [r for r in self.base.record.assignments if r.barrier_install_flag]
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0].displayed_assignment.label, ("G2", "I1"))

    def test_validator_rejects_same_post_installer_next_night(self):
        self.assertIn("15-3", rules(self.base.record, (self.previous,)))
        self.assertNotIn("15-3", rules(self.base.record, ()))

    def test_locked_past_install_is_kept(self):
        pid = next(iter(installers(self.base.record)))
        self.assertNotIn("15-3", rules(self.base.record, (self.previous,), locked=((pid, 2),)))

    def test_solver_moves_install_to_someone_else(self):
        out = run_schedule(request(), HistorySelection(actual_records=(self.previous,),
                                                       last_rest_records=(self.previous,)), OPTIONS)
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        self.assertEqual(out.prepared_inputs.forbid_install_ids, tuple(installers(self.previous)))
        self.assertTrue(installers(out.record))
        self.assertFalse(installers(out.record) & installers(self.previous))
        # 15-8 (10/19): 마지막 참여일이 오래된(기록 없는) 사람이 설치·철수 둘 다 먼저 맡는다
        self.assertEqual(len(duty_people(out.record)), 2)
        self.assertFalse(duty_people(out.record) & duty_people(self.previous))
        from night_shift.balance_notes import history_influence_lines
        text = "\n".join(history_influence_lines(out.record, out.employee_stats, out.prepared_inputs))
        self.assertIn("참여 기록 없음", text)
        self.assertIn("15-8", text)


if __name__ == "__main__":
    unittest.main()
