"""2026-10-13 사용자 요청: 야간 표 제목 줄 FM·유도리 보기 버튼. 처음은 FM, 유도리면 적용 시간대·포스트 테두리와
분석(전체 비교·직원 상세분석)을 유도리 기준으로. 배정은 그대로."""
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from night_shift import history_import as imp
from night_shift.models import GENERATION_POST_OPERATIONS, Mode
from night_shift.presentation import flexible_band
from night_shift.schedule_edit import record_grid_payload


def fm_record():
    grid = {p: ["휴게"] * 14 for p in ("A", "1", "2", "3", "4", "5", "6")}
    for t in range(14):
        grid["1"][t] = "I1"
    record = imp.build_import_record(date(2026, 10, 16), Mode.FM, grid, {p: p for p in grid}, imp.ROSTER)
    return replace(record, context=replace(record.context, post_operations=GENERATION_POST_OPERATIONS))


class FmFlexViewTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.patcher = patch("history_ui.st.session_state", self.state)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_toggle_default_fm_then_flexible_outline_and_stats(self):
        import history_ui
        record = fm_record()
        payload = record_grid_payload(record)
        self.assertEqual(history_ui.view_toggle(payload, record, "k"), "FM")       # 처음은 FM
        self.assertTrue(payload["view_toggle"])
        self.assertIsNone(payload["band"])
        self.assertFalse(any(any(v) for v in payload["sheet"]["operations"].values()))
        self.state["k"] = "유도리"
        payload = record_grid_payload(record)
        history_ui.view_toggle(payload, record, "k")
        self.assertEqual(payload["view_mode"], "유도리")
        self.assertEqual(payload["band"], (4, 10))                                  # 22~04시 시간 띠
        i1 = payload["sheet"]["operations"]["I1"]
        self.assertEqual([t for t, v in enumerate(i1) if v == "rest"], [4, 5, 6, 7, 8, 9])
        flex = history_ui.view_record(record, "k")                                  # 분석은 유도리로 다시 계산
        self.assertEqual(flex.context.effective_mode, Mode.FLEXIBLE)
        self.assertEqual([r.slot.index for r in flex.assignments if r.employee_id == "1" and r.actual_rest_time_value == 1],
                         [4, 5, 6, 7, 8, 9])
        self.assertEqual([(r.employee_id, r.slot.index, r.displayed_assignment.label) for r in flex.assignments],
                         [(r.employee_id, r.slot.index, r.displayed_assignment.label) for r in record.assignments])

    def test_flexible_generated_table_has_no_toggle(self):
        import history_ui
        record = fm_record()
        flex_made = replace(record, context=replace(record.context, requested_mode=Mode.FLEXIBLE, effective_mode=Mode.FLEXIBLE))
        payload = record_grid_payload(flex_made)
        history_ui.view_toggle(payload, flex_made, "k")
        self.assertNotIn("view_toggle", payload)
        self.assertEqual(flexible_band(flex_made.context), (4, 10))                # 유도리로 만든 표는 늘 띠 표시

    def test_view_event_switches_once(self):
        import history_ui
        with patch("history_ui.st.rerun") as rerun:
            self.assertTrue(history_ui.handle_view_event({"kind": "view", "mode": "유도리", "nonce": "n1"}, "k"))
            self.assertEqual(self.state["k"], "유도리")
            rerun.assert_called_once()
            self.state["k"] = "FM"                                                   # 새 생성으로 FM 초기화
            history_ui.handle_view_event({"kind": "view", "mode": "유도리", "nonce": "n1"}, "k")   # 같은 옛 이벤트
            self.assertEqual(self.state["k"], "FM")                                 # 다시 적용하지 않음
        self.assertFalse(history_ui.handle_view_event({"kind": "cell"}, "k"))


class NoteColorTests(unittest.TestCase):
    def test_more_less_lines_colored_and_summary(self):
        # 2026-10-13 사용자 요청: 그날 피로도를 많이/적게 받은 내용은 글자색으로, 맨 위 요약 한 줄
        import app
        record = fm_record()
        lines = app.note_lines_html(["· 1 광희: 오늘 피로도 14로 조금 더 맡겼습니다.",
                                     "· 원종 손해 보상: 1점 낮게 편성했습니다.", "연차: 준호."], record)
        self.assertIn("오늘 피로도", lines[0])
        self.assertIn(app.MORE_COLOR, lines[0]); self.assertIn(app.LESS_COLOR, lines[0])
        self.assertIn(f"color:{app.MORE_COLOR}", lines[1])
        self.assertIn(f"color:{app.LESS_COLOR}", lines[2])
        self.assertEqual(lines[3], "- 연차: 준호.")                       # 그 밖의 줄은 그대로
        self.assertNotIn("오늘 피로도", " ".join(app.note_lines_html(["x"], None)))

    def test_flexible_view_replaces_only_score_lines(self):
        # 2026-10-13 사용자 확정: 유도리 보기면 점수 줄(밸런스 판정)만 유도리 기준, 이유 설명 줄은 그대로
        import app
        record = fm_record()
        reasons = ["밸런스 판정 — 온전 출근 일반근무자 6명: 피로도 99~99점(차이 0) → 완전 n빵입니다.",
                   "· 피로도: 옛 설명", "과거 싸이클 영향 —", "· 원종 손해 보상: 1점 낮게 편성했습니다."]
        lines, flex = app.flexible_note_numbers(reasons, record)
        self.assertEqual(flex.context.effective_mode, Mode.FLEXIBLE)
        self.assertTrue(lines[0].startswith("밸런스 판정 —"))
        self.assertNotIn("99~99", " ".join(lines))                       # FM 숫자 → 유도리 숫자
        self.assertNotIn("· 피로도: 옛 설명", lines)
        self.assertEqual(lines[-2:], reasons[-2:])                         # 이유 설명은 그대로


if __name__ == "__main__":
    unittest.main()
