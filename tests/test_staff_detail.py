"""직원 분석의 표시 통계·특수업무·PC 최장 구간 회귀검증."""
import unittest
from datetime import date
from types import SimpleNamespace

import app
from night_shift.models import Mode, NightType, ShiftRecord, RecordKind, Posture
from night_shift.profiles import make_record
from night_shift.service import ShiftRequest, build_context, calculate_employee_stats


def fixture(mode):
    staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
    ctx = build_context(ShiftRequest(date(2026, 10, 3), NightType.N4, mode, staff))
    labels = {1: "G1", 2: "I1" if mode == Mode.FLEXIBLE else "보안실 대기",
              5: "lower", 7: "upper", 8: "middle", 9: "G1",
              10: "I1" if mode == Mode.FLEXIBLE else "보안실 대기"}
    rows = tuple(make_record(ctx, "1", t, labels.get(t, "휴게"),
                             install=t == 2, remove=t == 10, patrol_standing=True)
                 for t in range(14))
    record = ShiftRecord("detail-unit-fixture", RecordKind.PLAN, ctx, rows)
    stats = calculate_employee_stats(record, "1")
    return SimpleNamespace(record=record, employee_stats={"1": stats})


class StaffDetailTests(unittest.TestCase):
    def test_counts_only_pure_posts_and_keeps_actual_accounting(self):
        for mode in Mode:
            with self.subTest(mode=mode):
                result = fixture(mode)
                stats = result.employee_stats["1"]
                # 2026-10-05: I1 근무 중 겸임한 차단봉 칸(유도리 20시 I1)도 포스트라 좌식에 셈. 대기 차단봉(FM)은 제외
                self.assertEqual((stats.post_standing, stats.post_seated), (1, 1) if mode == Mode.FM else (1, 2))
                self.assertEqual(stats.standing, 4)  # 내부 이력·연속근무 의미 유지
                self.assertEqual(stats.fatigue_value, 10)
                # 11-0: FM 차단봉만 한 2칸(20·04시 보안실 대기)은 실근무 0. 유도리는 I1 포스트 겸임이라 그대로
                self.assertEqual((stats.actual_work_time_value, stats.actual_rest_time_value),
                                 (5, 7) if mode == Mode.FM else (7, 7))
                self.assertEqual(stats.patrol_fatigue, 5)
                self.assertEqual(stats.posture_by_post["I1"],
                                 {"standing": 0, "seated": 0 if mode == Mode.FM else 1})
                self.assertEqual(stats.fatigue_value, 2 * stats.post_standing + stats.post_seated
                                 + stats.patrol_fatigue + stats.other_fatigue)      # 피로도 = 입식×2 + 좌식 + 순찰 피로도 + 기타
                self.assertTrue(all(r.posture_or_mode == Posture.STANDING
                                    for r in result.record.assignments if r.slot.index in (5, 7, 8)))

    def test_special_states_show_fatigue_without_posture(self):
        for mode in Mode:
            result = fixture(mode)
            rows = {r.slot.index: r for r in result.record.assignments}
            self.assertEqual(app.person_actual_state(rows[5]), "순찰(피로도 1)")
            self.assertEqual(app.person_actual_state(rows[7]), "순찰(피로도 2)")
            self.assertEqual(app.person_actual_state(rows[2]), "차단봉 설치(피로도 1)")
            self.assertEqual(app.person_actual_state(rows[10]), "차단봉 철수(피로도 1)")
            self.assertEqual(app.person_actual_state(rows[1]), "입식")
            self.assertEqual(app.person_actual_state(rows[9]), "좌식")

    def test_pc_timeline_restores_all_tied_longest_windows(self):
        result = fixture(Mode.FM)
        stats = result.employee_stats["1"]
        html = app.person_timeline_html(result, "1")
        self.assertIn("class='person-timeline'", html)
        self.assertEqual(html.count("<th "), 14)
        self.assertIn("border:2px solid #0F172A", html)
        self.assertEqual(html.count("최장 근무"), sum(w.hours for w in stats.longest_actual_work))
        self.assertEqual(html.count("최장 휴게"), sum(w.hours for w in stats.longest_rest))
        self.assertIn("순찰(피로도 1)", html)
        mobile = app.person_schedule_html(result, "1")
        self.assertEqual(mobile.count("<tr>"), 14)
        self.assertNotIn("person-timeline", mobile)

    def test_install_with_post_keeps_its_original_fatigue(self):
        result = fixture(Mode.FLEXIBLE)
        ctx = app.replace(result.record.context, night_type=NightType.N1)
        row = make_record(ctx, "1", 2, "G2", install=True)
        self.assertEqual(row.fatigue_value, 2)  # 10-4: 포스트 겸임은 원래 회계, 1점으로 강제하지 않음
        self.assertEqual(app.person_actual_state(row), "차단봉 설치(피로도 2)")


if __name__ == "__main__":
    unittest.main()
