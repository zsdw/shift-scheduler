"""관리자 전반부 반차: 01시 출근·준호 전반부 대행·저장·독립 재검증."""
import unittest
from dataclasses import replace, asdict

from tests.test_manager_late_half import request, check_proxy_succession
from night_shift.models import AssignmentKind, Mode
from night_shift.history_store import record_to_json, record_from_json
from night_shift.service import (HistorySelection, SolveOptions, run_schedule_manager_early_half,
    revalidate, seat_form_record, display_form_record)


class ManagerEarlyHalfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.options = SolveOptions(rules_version='2.20', seconds=20, prefer_dual_mode=False)
        cls.result = run_schedule_manager_early_half(request(), HistorySelection(), cls.options)

    def test_generation_identity_and_actual_a_rules(self):
        r = self.result
        self.assertTrue(r.valid, r.validation_errors or r.solve_result.status)
        self.assertTrue(r.context.manager_handover_reverse)
        self.assertEqual(r.context.manager_handover, (7, '6'))
        rows = {(a.employee_id, a.slot.index): a for a in r.record.assignments}
        for t in range(14):
            self.assertEqual(rows['A', t].displayed_assignment.kind == AssignmentKind.UNAVAILABLE, t < 7)
            self.assertNotEqual(rows['6', t].displayed_assignment.kind, AssignmentKind.UNAVAILABLE)
        self.assertTrue(any(rows['A', t].displayed_assignment.label == 'I1' for t in range(7, 14)))
        self.assertLessEqual(sum(rows['A', t].displayed_assignment.label == '보안실 대기' for t in range(7, 14)), 2)
        self.assertNotIn(rows['A', 10].displayed_assignment.label, ('I1', '보안실 대기'))
        self.assertFalse(rows['A', 10].barrier_remove_flag)
        # 01~04시 네 칸 중 기존 관리자 3연속 실근무 금지 아래 최대 세 칸 근무.
        self.assertEqual(sum(rows['A', t].actual_work_time_value for t in range(7, 11)), 3)
        stage = next(a for a in r.solve_result.attempts if a.get('stage') == 'manager_early_active_work_max')
        self.assertEqual((stage['status'], stage['value']), ('OPTIMAL', -3))
        self.assertTrue(revalidate(r, r.record).valid)

    def test_proxy_day_total_gets_two_point_privilege(self):
        # 2026-10-18 사용자 확정: 전반부 반차 준호 하루 합계(대행 18~00시 + 자기 01~07시)는 피로도 2점 우대로 n빵
        r = self.result
        self.assertTrue(r.valid, r.validation_errors)
        s = r.employee_stats
        values = [s[p].fatigue_value for p in ('1', '2', '3', '4', '5')] + [s['6'].fatigue_value + 2]
        self.assertLessEqual(max(values) - min(values), 1, values)

    def test_serialization_and_seat_roundtrip_keep_reverse_direction(self):
        r = self.result
        self.assertTrue(r.valid, r.validation_errors)
        again = record_from_json(record_to_json(r.record))
        self.assertEqual(again, r.record)
        self.assertTrue(revalidate(r, again).valid)
        seat = seat_form_record(again)
        self.assertIsNone(seat.context.manager_handover)
        self.assertFalse(seat.context.manager_handover_reverse)
        self.assertEqual(display_form_record(seat, 7, '6', True), again)
        legacy = record_to_json(seat)
        del legacy['context']['manager_handover_reverse']
        self.assertFalse(record_from_json(legacy).context.manager_handover_reverse)

    def test_unavailable_a_and_four_oclock_i1_rejected(self):
        r = self.result
        self.assertTrue(r.valid, r.validation_errors)
        for t, label in ((0, 'I1'), (10, 'I1')):
            rows = list(r.record.assignments)
            ai = next(i for i, a in enumerate(rows) if a.employee_id == 'A' and a.slot.index == t)
            pi = next(i for i, a in enumerate(rows) if a.slot.index == t and a.displayed_assignment.label == label)
            a, p = rows[ai], rows[pi]
            rows[ai], rows[pi] = replace(p, employee_id='A'), replace(a, employee_id=p.employee_id)
            bad = revalidate(r, replace(r.record, assignments=tuple(rows)))
            self.assertFalse(bad.valid)
            if t == 10:
                self.assertTrue(any('8-10' in e['rule'] for e in bad.validation_errors), bad.validation_errors)

    def test_proxy_succession_fatigue_and_patrol(self):
        check_proxy_succession(self, self.result, range(7, 14))

    def test_proxy_must_work_full_night(self):
        with self.assertRaises(ValueError):
            run_schedule_manager_early_half(request(junho_half=True), HistorySelection(), self.options)

    def test_regeneration_uses_engine_form_exclusion(self):
        original = self.result
        self.assertTrue(original.valid, original.validation_errors)
        exclude = tuple(asdict(r) for r in seat_form_record(original.record).assignments)
        again = run_schedule_manager_early_half(request(), HistorySelection(),
            replace(self.options, exclude_assignments=exclude))
        self.assertTrue(again.valid, (again.solve_result.status, again.validation_errors))
        self.assertNotEqual(again.record.assignments, original.record.assignments)
        self.assertTrue(revalidate(again, again.record).valid)

    def test_flexible_and_one_absence(self):
        for mode, absent in ((Mode.FLEXIBLE, ()), (Mode.FM, ('3',)), (Mode.FLEXIBLE, ('3',))):
            with self.subTest(mode=mode, absent=absent):
                req = replace(request(absent=absent), requested_mode=mode)
                r = run_schedule_manager_early_half(req, HistorySelection(), self.options)
                self.assertTrue(r.valid, (r.solve_result.status, r.validation_errors))
                self.assertTrue(revalidate(r, r.record).valid)


class ManagerActualWindowTests(unittest.TestCase):
    def test_proxy_i1_before_arrival_does_not_satisfy_actual_a_minimum(self):
        from tests.test_a_i1_once import AI1OnceTests
        helper = AI1OnceTests()
        self.assertTrue(helper.errors(helper.record(2), manager_a_start_slot=7))
        self.assertFalse(helper.errors(helper.record(8), manager_a_start_slot=7))

    def test_proxy_standby_before_arrival_does_not_count_toward_a_cap(self):
        from tests.test_a_standby_cap import AStandbyCapTests
        helper = AStandbyCapTests()
        self.assertFalse(helper.errors(helper.record(4), manager_a_start_slot=7))


if __name__ == '__main__':
    unittest.main()
