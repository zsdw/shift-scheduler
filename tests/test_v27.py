import unittest
from dataclasses import replace
from run_v27 import context, posture_triples
from night_shift.models import HistoryInput
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


class V27Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = HistoryInput((), ())
        cls.result = solve_first_trial(context(), cls.history, seconds=30, rules_v27=True)
        cls.plan = cls.result.record
        assert cls.plan is not None

    def changed(self, labels):
        changes = {(p, t): make_record(self.plan.context, p, t, label) for p, t, label in labels}
        return replace(self.plan, assignments=tuple(changes.get((r.employee_id, r.slot.index), r) for r in self.plan.assignments))

    def test_generated_valid_with_zero_posture_triples(self):
        self.assertEqual(validate_first_trial(self.plan, self.history, rules_v27=True), [])
        self.assertEqual(posture_triples(self.plan), [])
        stage = next(a for a in self.result.attempts if a.get('stage') == 'same_posture_triples')
        self.assertEqual((stage['status'], stage['value']), ('OPTIMAL', 0))

    def test_evening_standing_triple_is_no_longer_hard_error(self):
        plan = self.changed([('1', 0, 'G2'), ('1', 1, 'G1'), ('1', 2, 'L3')])
        old = validate_first_trial(plan, self.history, rules_v26=True)
        new = validate_first_trial(plan, self.history, rules_v27=True)
        self.assertTrue(any(e['rule'] == 'H-06/H-07' and e['detail'].endswith('1/0') for e in old))
        self.assertFalse(any(e['rule'] == 'H-06/H-07' and e['detail'].endswith('1/0') for e in new))

    def test_morning_without_gate_still_hard_error(self):
        plan = self.changed([('1', 11, 'L3'), ('1', 12, 'G1'), ('1', 13, 'I1')])
        errors = validate_first_trial(plan, self.history, rules_v27=True)
        self.assertTrue(any(e['rule'] == 'H-06/H-07' and e['detail'].endswith('1/11') for e in errors))

    def test_posture_audit_distinguishes_seated_and_mixed(self):
        seated = self.changed([('1', 6, 'I1'), ('1', 7, 'G1'), ('1', 8, 'I1')])
        self.assertIn({'employee': '1', 'start_hour': 0, 'posture': 'seated'}, posture_triples(seated))
        mixed = self.changed([('1', 6, 'I1'), ('1', 7, 'L3'), ('1', 8, 'I1')])
        self.assertFalse(any(x['employee'] == '1' and x['start_hour'] == 0 for x in posture_triples(mixed)))
