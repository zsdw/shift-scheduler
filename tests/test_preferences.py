"""17-1 근무자 선호 (2026-10-02 사용자 확정). 모두 소프트.

- 공통 선호 보너스: 00~05시 2시간 이상 연속 휴게, 07시 휴게. 모두 기본 가중치 + 최근 3싸이클 실제 피로도가
  팀 평균보다 높았던 사람에게 더. 밸런스를 다 맞춘 뒤 적용.
- 개인 회피(강한 소프트): 만년 — 다음날이 평일인 야간(N1·N3) 06시 I1.
"""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import app
from night_shift import service
from night_shift.models import Mode, NightType
from night_shift.preferences import BASE_WEIGHT, avoid_cells, preference_weights
from night_shift.service import ShiftRequest, SolveOptions, build_context, run_schedule

OPTIONS = SolveOptions(rules_version="2.20", seconds=20)
N1, N2 = (date(2026, 10, 5), NightType.N1), (date(2026, 10, 9), NightType.N2)


def night(fatigue_by_id):
    rows = tuple(SimpleNamespace(employee_id=p, fatigue_value=f) for p, f in fatigue_by_id.items())
    attendance = tuple(SimpleNamespace(employee_id=p, present=True) for p in fatigue_by_id)
    return SimpleNamespace(context=SimpleNamespace(attendance=attendance), assignments=rows)


def request(day_night, mode=Mode.FM):
    staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
    return ShiftRequest(day_night[0], day_night[1], mode, staff)


def rest_flags(result, employee_id):
    rows = {r.slot.index: r for r in result.record.assignments if r.employee_id == employee_id}
    rest = [rows[t].actual_rest_time_value == 1 for t in range(14)]
    return any(rest[t] and rest[t + 1] for t in range(6, 11)), rest[13]


class PreferenceTests(unittest.TestCase):
    def test_weights_favor_people_with_higher_recent_actual_fatigue(self):
        records = [night({"1": 16, "2": 14, "3": 14}), night({"1": 16, "2": 14, "3": 14})]
        weights = preference_weights(records, ("1", "2", "3"))
        self.assertGreater(weights["1"], weights["2"])
        self.assertEqual(weights["2"], BASE_WEIGHT)
        self.assertEqual(preference_weights((), ("1", "2")), {"1": BASE_WEIGHT, "2": BASE_WEIGHT})

    def test_manyeon_06_i1_avoid_only_before_weekday(self):
        manyeon = next(eid for eid, name in app.ROSTER if name == "만년")
        self.assertEqual(avoid_cells(build_context(request(N1))), ((manyeon, 12, "I1"), ("A", 10, "보안실 대기")))
        self.assertEqual(avoid_cells(build_context(request(N2))), (("A", 10, "보안실 대기"),))

    def test_a04_avoid_all_modes_and_types_without_proxy_transfer(self):
        from dataclasses import replace
        for mode in Mode:
            for kind in NightType:
                context = build_context(request((date(2026, 10, 3), kind), mode))
                self.assertEqual([c for c in avoid_cells(context) if c[0] == "A"],
                                 [("A", 10, "보안실 대기")])
                context = replace(context, attendance=tuple(
                    replace(a, present=False) if a.employee_id == "A" else a
                    for a in context.attendance))
                self.assertFalse(any(c[2] == "보안실 대기" for c in avoid_cells(context)))

    def test_a04_avoid_is_soft_when_actual_cell_is_locked(self):
        from dataclasses import replace
        from night_shift.profiles import make_record
        req = request(N1)
        context = build_context(req)
        slot = 10
        # 15-0·8-10(2026-10-05): 보안실 대기 철수와 통제A 철수는 더 이상 만들 수 없다. 잠긴 실제 04시 칸 보존만 확인.
        with self.assertRaises(ValueError):
            make_record(context, "A", slot, "보안실 대기", remove=True)
        locked = make_record(context, "A", slot, "휴게")
        result = run_schedule(req, None, replace(OPTIONS, locked_assignments=(locked,), prefer_dual_mode=False))
        self.assertTrue(result.valid, result.validation_errors)
        row = next(r for r in result.record.assignments if r.employee_id == "A" and r.slot.index == 10)
        self.assertEqual(row, locked)

    def test_generation_respects_avoid_and_gives_preferences(self):
        manyeon = next(eid for eid, name in app.ROSTER if name == "만년")
        favored = next(eid for eid, name in app.ROSTER if name == "광희")
        real = service.prepare_engine_inputs

        def prepare(context, selection):              # 광희가 최근 3싸이클에서 손해 본 상황
            prepared = real(context, selection)
            weights = {p: BASE_WEIGHT for p in prepared.preference_weights}
            weights[favored] = BASE_WEIGHT + 6
            return service.replace(prepared, preference_weights=weights)
        with patch.object(service, "prepare_engine_inputs", side_effect=prepare):
            result = run_schedule(request(N1), None, OPTIONS)
        self.assertTrue(result.valid, result.validation_errors)
        stages = [a.get("stage") for a in result.solve_result.attempts]
        self.assertIn("personal_avoid", stages)
        a04 = next(r for r in result.record.assignments if r.employee_id == "A" and r.slot.index == 10)
        self.assertNotEqual(a04.displayed_assignment.label, "보안실 대기")
        self.assertIn("preference_bonus", stages)
        i1_06 = next(r.employee_id for r in result.record.assignments
                     if r.slot.index == 12 and r.displayed_assignment.label == "I1")
        self.assertNotEqual(i1_06, manyeon)                                   # 만년 06시 I1 회피
        self.assertTrue(rest_flags(result, favored)[0])           # 손해 본 사람: 두 선호 모두


if __name__ == "__main__":
    unittest.main()


