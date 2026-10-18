import unittest
from dataclasses import replace
from run_trial import context
from night_shift.models import HistoryInput, Mode
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from night_shift.profiles import make_record


class V22Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = HistoryInput((), ())
        cls.result = solve_first_trial(context(Mode.FM), cls.history, refinement=True, minimize_a=True, rules_v22=True, seconds=10)
        cls.plan = cls.result.record
        if cls.plan is None:
            raise AssertionError(cls.result.status)

    def test_new_plan_and_gap(self):
        self.assertEqual(validate_first_trial(self.plan, self.history, refinement=True, rules_v22=True), [])
        self.assertTrue(self.result.targets_met)
        hours = {p: sum(r.actual_work_time_value for r in self.plan.assignments if r.employee_id == p) for p in ['1','2','3','4','5','6','A']}
        self.assertEqual(hours['A'], 7)
        self.assertTrue(all(abs(hours[p]-hours['A']) <= 2 for p in hours))

    def changed(self, p, t, label):
        new = make_record(self.plan.context, p, t, label)
        return replace(self.plan, assignments=tuple(new if r.employee_id == p and r.slot.index == t else r for r in self.plan.assignments))

    def test_duplicate_evening_gate_rejected(self):
        p = next(r.employee_id for r in self.plan.assignments if r.slot.index == 0 and r.displayed_assignment.label == 'G3')
        errors = validate_first_trial(self.changed(p, 1, 'G2'), self.history, refinement=True, rules_v22=True)
        self.assertTrue(any(e['rule'] == 'H-14' for e in errors))

    def test_a_evening_gate_rejected(self):
        errors = validate_first_trial(self.changed('A', 2, 'G2'), self.history, refinement=True, rules_v22=True)
        self.assertTrue(any(e['rule'] == 'H-14' for e in errors))

    def test_excess_work_gap_rejected(self):
        bad = replace(self.plan, assignments=tuple(make_record(self.plan.context, 'A', r.slot.index, '휴게') if r.employee_id == 'A' else r for r in self.plan.assignments))
        errors = validate_first_trial(bad, self.history, refinement=True, rules_v22=True)
        self.assertTrue(any(e['rule'] == 'H-15' for e in errors))
