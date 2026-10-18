"""룰북 0-2-1 (2026-10-02 사용자 확정): FM을 고르면
1단계 두 기준 하드룰 + 두 기준 당일 목표(일반근무자 피로도 차이 1점·실휴게 차이 1시간 이하)
→ 2단계 두 기준 하드룰 → 3단계 FM만. 유도리 판정은 유도리로 다시 계산한 표를 독립 Validator로 확인한다."""
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import app
from night_shift import service
from night_shift.models import Mode, NightType, Posture
from night_shift.service import (ShiftRequest, SolveOptions, daily_spreads, flexible_view, run_schedule,
                                 validator_flags_for)
from night_shift.validator import validate_first_trial

OPTIONS = SolveOptions(rules_version="2.20", seconds=20)
N4 = (date(2026, 10, 3), NightType.N4)


def staff(absent=None):
    return app.staff_for_input(True, {eid: eid != absent for eid, _ in app.ROSTER})


def request(day_night=N4, absent="1", mode=Mode.FM):
    return ShiftRequest(day_night[0], day_night[1], mode, staff(absent))


def flexible_errors(result):
    # H-18은 실제 운영 모드에만 적용. 유도리 참고 표는 룰북과 서비스의 독립 재검증 조건을 따른다.
    return validate_first_trial(flexible_view(result.record), result.prepared_inputs.engine_history,
                                forbid_patrol_exclusion_ids=result.prepared_inputs.forbid_patrol_exclusion_ids,
                                work_spread=False,
                                **validator_flags_for("2.20", False))


def failing(levels):
    """주어진 단계에서는 해가 없는 상황을 흉내."""
    real = service._run_schedule_once

    def run(context, history, config, *, dual):
        result = real(context, history, config, dual=0 if dual in levels else dual)
        if dual in levels:
            return replace(result, solve_result=replace(result.solve_result, status="INFEASIBLE", record=None))
        return result
    return run


class DualModeTests(unittest.TestCase):
    def test_fm_one_absence_is_valid_and_balanced_in_both_modes(self):
        # 10/15 사례: 하드룰만 보면 유도리 기준 일반근무자 피로도 14~16(차이 2)이 될 수 있었음
        for day_night in (N4, (date(2026, 10, 5), NightType.N1)):
            result = run_schedule(request(day_night), None, OPTIONS)
            self.assertTrue(result.valid, result.validation_errors)
            self.assertIs(result.dual_mode, True)
            self.assertIs(result.dual_balanced, True)
            self.assertEqual(result.record.context.effective_mode, Mode.FM)       # 저장되는 표는 FM 그대로
            self.assertEqual(flexible_errors(result), [])                          # 유도리 Validator도 0건
            for spreads in (daily_spreads(result.record), daily_spreads(flexible_view(result.record))):
                self.assertLessEqual(spreads["피로도"], 1, spreads)
                self.assertLessEqual(spreads["실휴게"], 1, spreads)
            self.assertEqual(result.dual_spreads["유도리"], daily_spreads(flexible_view(result.record)))
            i1_rest = {r.slot.index for r in flexible_view(result.record).assignments
                       if r.displayed_assignment.label == "I1" and r.posture_or_mode == Posture.REST_LIKE}
            self.assertEqual(i1_rest, {4, 5, 6, 7, 8, 9})

    def test_second_level_when_balance_targets_impossible(self):
        with patch.object(service, "_run_schedule_once", side_effect=failing({2})) as spy:
            result = run_schedule(request(), None, OPTIONS)
        self.assertEqual([c.kwargs["dual"] for c in spy.call_args_list], [2, 1])
        self.assertTrue(result.valid)
        self.assertIs(result.dual_mode, True)
        self.assertEqual(flexible_errors(result), [])
        self.assertEqual(set(result.dual_spreads), {"FM", "유도리"})

    def test_falls_back_to_fm_only_when_dual_is_impossible(self):
        with patch.object(service, "_run_schedule_once", side_effect=failing({2, 1})) as spy:
            result = run_schedule(request(), None, OPTIONS)
        self.assertEqual([c.kwargs["dual"] for c in spy.call_args_list], [2, 1, 0])
        self.assertTrue(result.valid)
        self.assertIs(result.dual_mode, False)

    def test_not_applied_to_flexible_or_when_turned_off(self):
        flexible = run_schedule(request(mode=Mode.FLEXIBLE), None, OPTIONS)
        self.assertTrue(flexible.valid)
        self.assertIsNone(flexible.dual_mode)
        off = run_schedule(request(), None, replace(OPTIONS, prefer_dual_mode=False))
        self.assertTrue(off.valid)
        self.assertIsNone(off.dual_mode)


if __name__ == "__main__":
    unittest.main()
