"""대폭 휴게 (2026-10-20 사용자 확정, 아르곤 제안 1~4 추천안).

- 대폭 휴게 = 23시~07시 전(칸 5~12) 안에서 3시간 이상 연속 실휴게(models.BIG_REST_SLOTS).
- [하드 16-big] 그날 막타임(07시) 휴게를 받는 일반근무자는 대폭 휴게 동시 금지(통제A·준호 대행 제외, 전부 LOCK이면 보존).
- [소프트] 결원 1.5명 미만 날: 대폭 휴게 인원 최대 → 순번(한 번도 안 받은 사람 먼저·출근 많은 순, 그다음 마지막 수혜
  뒤 본인 출근 많은 순). 하층 순번 다음, 당일 균형 앞. 직전 출근 수혜자도 금지는 아니고 순번만 뒤.
- 저장표 '이날 실제 운영: 유도리로 근무함' = 그 표의 유도리 운영값을 포스트별 실제 운영 수정으로 저장 → 이력 집계에 반영.
"""
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from night_shift import history_import as imp
from night_shift import history_store
from night_shift.actual_edit import add_state_edit, apply_edits
from night_shift.models import BIG_REST_STARTS, HistoryInput, Mode, NightType, RecordKind
from night_shift.service import HistorySelection, ShiftRequest, run_schedule
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from tests.test_proxy_lowest import DAY, OPTIONS, staff


def _record(day: date, last_rest_pid: str = "1", big_rest_pids=(), i1_late_pid: str | None = None):
    grid = {p: ["G1"] * 14 for p in ("A", "1", "2", "3", "4", "5", "6")}
    grid[last_rest_pid][13] = "휴게"
    for bp in big_rest_pids:
        for t in (6, 7, 8):
            grid[bp][t] = "휴게"
    if i1_late_pid is not None:
        for t in (6, 7, 8):
            grid[i1_late_pid][t] = "I1"
    r = imp.build_import_record(day, Mode.FM, grid, {p: p for p in grid}, imp.ROSTER)
    return replace(r, kind=RecordKind.ACTUAL, confirmed_at=datetime(2026, 10, 16))


def _big_rest_ids(record) -> set[str]:
    rest = {(r.employee_id, r.slot.index) for r in record.assignments if r.actual_rest_time_value == 1}
    people = {r.employee_id for r in record.assignments if r.employee_id != "A"}
    return {p for p in people if any(all((p, t) in rest for t in (s, s + 1, s + 2)) for s in BIG_REST_STARTS)}


def _last_rest_ids(record) -> set[str]:
    return {r.employee_id for r in record.assignments
            if r.employee_id != "A" and r.slot.index == 13 and r.actual_rest_time_value == 1}


class BigRestRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n1 = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff()), HistorySelection(), OPTIONS)

    def test_generation_maximizes_big_rest_without_last_rest_overlap(self):
        self.assertTrue(self.n1.valid, self.n1.validation_errors)
        big, last = _big_rest_ids(self.n1.record), _last_rest_ids(self.n1.record)
        self.assertGreaterEqual(len(big), 4, big)                 # 평일 전날 결원 0명: 막타임 1명 빼고 대부분 받음
        self.assertFalse(big & last, (big, last))
        stage = next(a for a in self.n1.solve_result.attempts if a.get("stage") == "big_rest_max")
        self.assertEqual(stage["value"], -len(big))
        four_stage = next(a for a in self.n1.solve_result.attempts if a.get("stage") == "four_hour_runs")
        self.assertEqual(four_stage["value"], 0)
        stages = [a.get("stage") for a in self.n1.solve_result.attempts if isinstance(a, dict)]
        self.assertLess(stages.index("four_hour_runs"), stages.index("big_rest_max"))

    def test_validator_rejects_last_rest_and_big_rest_overlap_unless_locked(self):
        overlap = replace(_record(date(2026, 10, 15), last_rest_pid="1", big_rest_pids=("1",)),
                          kind=RecordKind.PLAN, confirmed_at=None)
        errors = validate_first_trial(overlap, HistoryInput((), ()), rules_v220=True)
        self.assertTrue(any(e["rule"] == "16-big" for e in errors))
        locked_ok = validate_first_trial(overlap, HistoryInput((), ()), rules_v220=True,
                                         locked_cells=(("1", 6), ("1", 7), ("1", 8), ("1", 13)))
        self.assertFalse(any(e["rule"] == "16-big" for e in locked_ok))

    def test_vacancy_one_and_half_has_no_big_rest_goal(self):
        # 결원 1명 + 반차 1명 = 1.5명 이상: 대폭 휴게 목표를 두지 않는다(다른 소프트 우선). 16-big 하드는 그대로.
        rows = [replace(s, available_slot_indices=tuple(range(7))) if s.employee_id == "3" else s
                for s in staff(absent=("2",))]
        result = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, tuple(rows)), HistorySelection(), OPTIONS)
        self.assertTrue(result.valid, result.validation_errors)
        self.assertFalse(any(str(a.get("stage", "")).startswith("big_rest") for a in result.solve_result.attempts))

    def test_rotation_prefers_never_received_and_counts_flexible_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            # 지난 FM 근무: '2'는 00~02시 I1, '3'·'4'는 00~02시 휴게. 그날을 '유도리로 근무함'(I1 22~03시 휴게성)으로 저장.
            d_past = date(2026, 10, 15)
            plan_past = replace(_record(d_past, last_rest_pid="1", big_rest_pids=("3", "4"), i1_late_pid="2"),
                                kind=RecordKind.PLAN, confirmed_at=None)
            history_store.save_confirmed(store, plan_past, "2.20")
            self.assertNotIn("2", _big_rest_ids(history_store.actual_record(store, d_past)))
            history_store.save_edits(store, d_past, add_state_edit([], "I1", 4, 9, "rest"))
            actual_past = history_store.actual_record(store, d_past)
            self.assertEqual(_big_rest_ids(actual_past), {"2", "3", "4"})   # 유도리 I1 휴게성으로 '2'도 수혜로 집계

            # 다음 근무: 한 번도 안 받은 1·5·6이 먼저('1'은 직전 막타임 수혜자지만 대폭 휴게는 순번만 적용)
            target = _record(date(2026, 10, 22), last_rest_pid="5")
            solved = solve_first_trial(target.context, HistoryInput((), ()), seconds=15, rules_v220=True,
                                       last_rest_records=(actual_past,))
            self.assertIsNotNone(solved.record, solved.status)
            stages = [a["stage"] for a in solved.attempts if str(a.get("stage", "")).startswith("big_rest_oldest_")]
            self.assertTrue(stages and stages[0].startswith("big_rest_oldest_0_"), stages)
            big_today, last_today = _big_rest_ids(solved.record), _last_rest_ids(solved.record)
            self.assertFalse(big_today & last_today)
            self.assertTrue(({"1", "5", "6"} - last_today) <= big_today, (big_today, last_today))
            self.assertFalse(any(e["rule"] == "16-big"
                                 for e in validate_first_trial(solved.record, HistoryInput((), ()), rules_v220=True)))


class FlexActualModeTests(unittest.TestCase):
    def test_toggle_adds_and_removes_only_flex_operation(self):
        from history_ui import flex_applied, night_flex_operations, toggle_flex
        plan = run_schedule(ShiftRequest(DAY, NightType.N1, Mode.FM, staff()), HistorySelection(), OPTIONS).record
        ops = night_flex_operations(plan)
        self.assertEqual(ops, (("I1", 4, 9, "rest"),))           # 새 생성 표 = I1 22~03시 휴게성
        other = {"type": "fatigue", "cell": ["1", 3], "value": 1, "note": ""}
        on = toggle_flex([other], ops, True)
        self.assertTrue(flex_applied(on, ops))
        i1 = [r for r in apply_edits(plan, on).assignments
              if r.displayed_assignment.label == "I1" and 4 <= r.slot.index <= 9]
        self.assertTrue(i1 and all(r.actual_rest_time_value == 1 for r in i1))   # I1 칸이 실휴게 → 대폭 휴게 집계에 들어감
        off = toggle_flex(on, ops, False)
        self.assertEqual(off, [other])                           # 다른 수정은 그대로
        self.assertFalse(flex_applied(off, ops))
        old = replace(plan, context=replace(plan.context, post_operations=None))
        self.assertEqual(night_flex_operations(old), (("I1", 6, 9, "rest"),))   # 옛 저장본(None) = 종전 00~03시


if __name__ == "__main__":
    unittest.main()
