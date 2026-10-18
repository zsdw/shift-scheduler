"""유도리 포스트별 운영 (사용자 지정, 2026-10-02 사용자 확정).

- None이면 룰북 기본 유도리(10-1: I1 00~03시 휴게성) 그대로.
- 지정하면 그 포스트·시간을 휴게성(10-1 휴게성 I1과 같은 취급) 또는 좌식으로 계산해 밸런스를 맞춘다.
- 남문(G2·G3)은 휴게성만, G1·L3는 좌식만, I1은 둘 다. 20시 설치·04시 철수 칸은 룰북대로.
"""
import unittest
from dataclasses import replace
from datetime import date

import app
from night_shift.history_store import record_from_json, record_to_json
from night_shift.models import Mode, NightType, Posture
from night_shift.service import ShiftRequest, SolveOptions, revalidate, run_schedule

OPTIONS = SolveOptions(rules_version="2.20", seconds=30)
DAY = date(2026, 10, 5)
CUSTOM = (("I1", 4, 9, "rest"), ("G1", 11, 13, "seated"), ("L3", 8, 10, "seated"), ("G2", 13, 13, "rest"))


def staff():
    return app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})


def solve(operations, night=NightType.N1):
    return run_schedule(ShiftRequest(DAY, night, Mode.FLEXIBLE, staff(), post_operations=operations), None, OPTIONS)


def postures(result, label):
    out = {}
    for r in result.record.assignments:
        if r.displayed_assignment.label == label and r.displayed_assignment.kind.value == "post":
            out.setdefault(r.slot.index, set()).add(r.posture_or_mode)
    return out


class FlexibleOperationTests(unittest.TestCase):
    def test_default_is_rulebook_flexible(self):
        # 2026-10-13 사용자 확정: 새 생성 기본 I1 22~03시(4~9) 휴게성 (종전 None 저장본만 00~03시)
        result = solve(None)
        self.assertTrue(result.valid, result.validation_errors)
        i1 = postures(result, "I1")
        self.assertEqual([t for t in range(14) if Posture.REST_LIKE in i1.get(t, ())], [4, 5, 6, 7, 8, 9])

    def test_custom_operations_are_applied_and_validated(self):
        result = solve(CUSTOM)
        self.assertTrue(result.valid, result.validation_errors)
        i1, g1, l3, g2 = (postures(result, p) for p in ("I1", "G1", "L3", "G2"))
        self.assertEqual([t for t in range(14) if Posture.REST_LIKE in i1.get(t, ())], [4, 5, 6, 7, 8, 9])
        self.assertTrue(all(g1[t] == {Posture.SEATED} for t in (11, 12, 13)))
        self.assertTrue(all(l3[t] == {Posture.SEATED} for t in (8, 9, 10)))
        self.assertIn(Posture.REST_LIKE, g2[13])
        self.assertNotEqual(i1[10], {Posture.REST_LIKE})               # 04시 I1 철수는 룰북대로
        for r in result.record.assignments:                             # 휴게성 칸: 피로도 0·실근무 0·실휴게 1
            if r.displayed_assignment.kind.value == "post" and r.posture_or_mode == Posture.REST_LIKE \
                    and r.displayed_assignment.label != "L3":
                self.assertEqual((r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value), (0, 0, 1))
        notes = " ".join(result_notes(result))
        self.assertIn("유도리 포스트별 운영", notes)

    def test_validator_rejects_accounting_that_ignores_the_operations(self):
        result = solve(CUSTOM)
        self.assertTrue(result.valid)
        # 같은 표를 '룰북 기본 유도리'로 검증하면 22·23시 I1 휴게성 등 회계가 맞지 않아야 한다
        tampered = replace(result.record, context=replace(result.record.context, post_operations=None))
        self.assertTrue(revalidate(result, tampered).validation_errors)

    def test_disallowed_combinations_are_rejected(self):
        for bad in ((("G1", 6, 9, "rest"),), (("L3", 6, 9, "rest"),), (("G2", 12, 13, "seated"),),
                    (("I1", 9, 6, "rest"),)):
            with self.assertRaises(ValueError, msg=bad):
                solve(bad)

    def test_operations_saved_with_record(self):
        result = solve(CUSTOM)
        loaded = record_from_json(record_to_json(result.record))
        self.assertEqual(loaded.context.post_operations, CUSTOM)
        # 새 표는 기본 운영값을 명시 저장(과거 None 저장본과 구분) — 2026-10-13
        from night_shift.models import GENERATION_POST_OPERATIONS
        self.assertEqual(record_from_json(record_to_json(solve(None).record)).context.post_operations, GENERATION_POST_OPERATIONS)


def result_notes(result):
    from night_shift.balance_notes import balance_reasons
    return balance_reasons(result.record, result.employee_stats, result.prepared_inputs)


if __name__ == "__main__":
    unittest.main()
