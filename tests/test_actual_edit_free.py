"""2026-10-21 사용자 확정: 저장본 실제 근무 수정은 규칙으로 막지 않는다. 피로도는 옮겨 간 칸 기준으로 다시 세고,
차단봉 담당(10/09~ 단독)은 바뀐 표에서 20시 G2(없으면 I1)·04시 I1로 다시 정한다. 수정으로 새로 생긴
하드·강한 권장 위반만 특이사항·비고 맨 위에 짧게 적는다(edit_violations)."""
import unittest
from datetime import date

from night_shift.actual_edit import apply_edits, edit_violations
from night_shift.models import AssignmentKind as K, Mode, NightType
from night_shift.profiles import make_record
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def rows(record):
    return {(r.employee_id, r.slot.index): r for r in record.assignments}


class ActualEditFreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
        cls.result = run_schedule(ShiftRequest(date(2026, 10, 27), NightType.N1, Mode.FM, tuple(staff)),
                                  HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
        assert cls.result.valid, cls.result.validation_errors
        cls.plan = cls.result.record

    def installers(self, record, slot, flag):
        return [r for r in record.assignments if r.slot.index == slot and getattr(r, flag)]

    def test_no_change_no_violation_lines(self):
        self.assertEqual(edit_violations(self.plan, self.plan), [])

    def test_installer_moved_to_other_hour_is_allowed_and_reassigned(self):
        r = rows(self.plan)
        installer = self.installers(self.plan, 2, "barrier_install_flag")[0]
        rester = next(p for p in NAMES if r[(p, 3)].displayed_assignment.label == "휴게")
        actual = apply_edits(self.plan, [{"type": "swap", "a": [installer.employee_id, 2], "b": [rester, 3]}])
        new = self.installers(actual, 2, "barrier_install_flag")
        self.assertEqual(len(new), 1)
        labels_20 = {x.displayed_assignment.label for x in actual.assignments if x.slot.index == 2}
        self.assertEqual(new[0].displayed_assignment.label, "G2" if "G2" in labels_20 else "I1")
        self.assertFalse(any(x.barrier_install_flag for x in actual.assignments if x.slot.index != 2))
        moved = rows(actual)[(rester, 3)]
        self.assertEqual(moved.displayed_assignment.label, installer.displayed_assignment.label)
        self.assertFalse(moved.barrier_install_flag)

    def test_same_hour_swap_moves_install_to_new_g2(self):
        r = rows(self.plan)
        g2 = next((p for p in [*NAMES, "A"] if r[(p, 2)].displayed_assignment.label == "G2"), None)
        if g2 is None:
            self.skipTest("20시 G2 없음")
        other = next(p for p in NAMES if p != g2 and r[(p, 2)].displayed_assignment.kind in (K.REST, K.SECURITY_STANDBY))
        actual = apply_edits(self.plan, [{"type": "swap", "a": [g2, 2], "b": [other, 2]}])
        self.assertEqual([x.employee_id for x in self.installers(actual, 2, "barrier_install_flag")], [other])

    def test_post_moved_to_hour_without_that_post_is_counted(self):
        r = rows(self.plan)
        hour_labels = {t: {x.displayed_assignment.label for x in self.plan.assignments if x.slot.index == t}
                       for t in range(14)}
        found = next(((p, t, u, x.displayed_assignment.label) for (p, t), x in r.items()
                      if p != "A" and t not in (2, 10) and x.displayed_assignment.kind in (K.POST, K.PATROL)
                      for u in range(14) if u not in (2, 10)
                      and x.displayed_assignment.label not in hour_labels[u]
                      and r[(p, u)].displayed_assignment.label == "휴게"), None)
        self.assertIsNotNone(found)          # 예전에는 '그 시간에 없는 근무'라 막혔던 교환
        p, t, u, label = found
        actual = apply_edits(self.plan, [{"type": "swap", "a": [p, t], "b": [p, u]}])
        cell = rows(actual)[(p, u)]
        self.assertEqual(cell, make_record(self.plan.context, p, u, label, patrol_standing=True))
        self.assertGreater(cell.fatigue_value, 0)
        self.assertEqual(calculate_all_stats(actual)[p].fatigue_value,
                         sum(x.fatigue_value for x in actual.assignments if x.employee_id == p))

    def test_new_hard_violation_is_listed(self):
        r = rows(self.plan)
        worker = next(p for p in NAMES if r[(p, 11)].actual_work_time_value == 1 and r[(p, 11)].displayed_assignment.kind == K.POST)
        actual = apply_edits(self.plan, [{"type": "swap", "a": ["A", 11], "b": [worker, 11]}])
        lines = edit_violations(self.plan, actual)
        self.assertTrue(any(line.startswith("하드 · ") for line in lines), lines)

    def test_new_strong_soft_violation_is_listed(self):
        r = rows(self.plan)
        # 누군가의 휴게 칸을 근무와 맞바꿔 4시간 연속 실휴게 또는 입식 3연속을 만든다 — 최초 표에 없던 것만 나와야 함
        lines = []
        for p in NAMES:
            for t in range(13):
                a, b = r[(p, t)], r[(p, t + 1)]
                if a.actual_work_time_value == 1 and b.actual_rest_time_value == 1 and t not in (2, 10) and t + 1 not in (2, 10):
                    actual = apply_edits(self.plan, [{"type": "swap", "a": [p, t], "b": [p, t + 1]}])
                    lines = [x for x in edit_violations(self.plan, actual) if x.startswith("강한 권장 · ")]
                    if lines:
                        break
            if lines:
                break
        self.assertTrue(lines)
        self.assertFalse(any("[" in x for x in lines))          # 규칙 코드 없이 사람·시간·뜻만


    def test_saved_screen_saves_violating_swap_and_lists_it_pc_and_mobile(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from streamlit.testing.v1 import AppTest

        from night_shift import history_store
        app = str(Path(__file__).resolve().parents[1] / "app.py")
        day = self.plan.context.shift_start_date
        r = rows(self.plan)
        worker = next(p for p in NAMES if r[(p, 11)].actual_work_time_value == 1 and r[(p, 11)].displayed_assignment.kind == K.POST)
        swap = {"type": "swap", "a": ["A", 11], "b": [worker, 11]}           # 관리자 05시 휴게 깨짐(하드)
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                history_store.save_confirmed(Path(folder), self.plan, "2.20")
                at = AppTest.from_file(app, default_timeout=240)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = day
                at.run()

                def fake(component, **kw):
                    if component.name.endswith("drag_schedule") and kw.get("key") == f"saved_grid_{day}":
                        return {"kind": "cell", "source": swap["a"], "target": swap["b"], "nonce": f"c-{view}"}
                    return None
                with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True,
                           side_effect=fake):
                    at.run()
                self.assertFalse(at.exception)
                text = " ".join(m.value for m in at.markdown)
                self.assertIn("실제 수정으로 생긴 규칙 위반", text)
                self.assertIn("관리자 05시 휴게", text)
                at.button(key=f"saved_save_{day}").click().run()
                self.assertEqual(history_store.load(Path(folder), day)["edits"], [swap])


if __name__ == "__main__":
    unittest.main()
