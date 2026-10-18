import unittest
from dataclasses import replace

from night_shift.models import HistoryInput, NightType
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from run_sep28_n2_fm import context


class V212Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = context(NightType.N3)
        cls.history = HistoryInput((), ())
        result = solve_first_trial(cls.context, cls.history, seconds=15, rules_v212=True)
        if result.record is None:
            raise AssertionError(result.attempts)
        cls.record = result.record

    def test_n3_hard_rules_and_rest_preference(self):
        self.assertEqual(validate_first_trial(self.record, self.history, rules_v212=True), [])
        for hour, expected in ((2, 2), (10, 1)):
            self.assertEqual(sum(r.slot.index == hour and r.displayed_assignment.label == "보안실 대기"
                                 for r in self.record.assignments), expected)
        for person in ("1", "2", "3", "4", "5", "6", "A"):
            rows = sorted((r for r in self.record.assignments if r.employee_id == person), key=lambda r: r.slot.index)
            self.assertFalse(any(all(r.actual_rest_time_value for r in rows[i:i+4]) for i in range(11)))

    def test_validator_detects_extra_04_standby_and_previous_patrol_exclusion(self):
        original = next(r for r in self.record.assignments if r.slot.index == 10 and r.displayed_assignment.label == "휴게")
        replacement = make_record(self.context, original.employee_id, 10, "보안실 대기", patrol_standing=True)
        altered = replace(self.record, assignments=tuple(replacement if r is original else r for r in self.record.assignments))
        self.assertTrue(any(e["rule"] == "H-16" for e in validate_first_trial(altered, self.history, rules_v212=True)))
        excluded = next(p for p in ("1", "2", "3", "4", "5", "6") if not any(
            r.employee_id == p and r.actual_post_or_work_type.kind == "patrol" for r in self.record.assignments))
        self.assertTrue(any(e["rule"] == "§14-1" for e in validate_first_trial(
            self.record, self.history, rules_v212=True, forbid_patrol_exclusion_ids=(excluded,))))


if __name__ == "__main__":
    unittest.main()
