"""2026-10-22 사용자 확정: 특이사항·비고 정리 — 📌 오늘 한눈에 / 🔄 순번으로 정한 것(줄을 누르면 표) /
🛡 규칙 때문에 바뀐 것 / ⚖️ 밸런스 자세히(스위치). 문장 내용은 그대로, 저장 당시 문장도 같은 규칙으로 묶는다."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app

LINES_1022 = [   # 10/22 저장 당시 문장(스냅샷) 그대로
    "밸런스 판정 — 온전 출근 일반근무자 6명: 피로도 13~14점(차이 1), 실휴게 5~6시간(차이 1).",
    "· 피로도: 합계 82점을 6명이 나누면 4점이 남아 똑같이 나눌 수 없습니다. 차이 1점이 가능한 최소입니다.",
    "· 실휴게: 합계 35시간을 6명이 나누면 5시간이 남아 똑같이 나눌 수 없습니다. 차이 1시간이 가능한 최소입니다.",
    "포스트 고루 배정(17-2): 모두 G1·L3·I1을 1번 이상 섰습니다 · 사람별 횟수 G1 2~2회, L3 1~2회, I1 2~3회.",
    "마지막 휴게(07시): 2 준호(이번 이전 마지막 수혜 10/04) · 직전 근무 07시 휴게자(4 만년)는 새 편성에서 연속 수혜 금지(16장).",
    "과거 싸이클 영향 —",
    "· 1 성호: 직전 근무에서 차단봉을 설치해 오늘 차단봉 설치에서 뺐습니다(15-3).",
    "· 5 원종: 순찰 제외 후 야간·공휴일 주간 출근 2회 보호 대상이라 오늘 순찰을 맡겼습니다(14-1-2).",
    "· 차단봉: 오래 기다린 순서대로 5 원종(마지막 10/10 뒤 출근 3회)에게 오늘 맡겼습니다(15-8, 막타임 다음 우선).",
    "· 대폭 휴게(23시~07시 전 3시간 이상 연속 휴게): 가능한 많은 사람에게, 오래 기다린 순서대로 4 만년에게 오늘 줬습니다.",
    "· 상층 순찰: 최근 6근무(야간·공휴일 주간) 근무당 횟수가 팀 평균(0.18)보다 적은 1 성호(0.00)에게 오늘 맡겼습니다(15-8).",
    "통제A 피로도 격차 3점 예외: 만년, 원종 — 다른 권장 목표를 먼저 적용하고, 통제A와의 0~2점 차이는 마지막 순위로 맞춥니다.",
    "근무자 선호(17-1): 00~05시 2시간 이상 연속 휴게 — 만년 · 07시 휴게 — 준호. (밸런스를 다 맞춘 뒤 남는 선택지에서 반영)",
    "만년 06시 I1 회피(개인 선호): 반영했습니다.",
    "통제 04시 보안실 대기 회피(개인 선호): 반영했습니다.",
    "FM·유도리 모두 만족하는 표입니다: 두 기준 모두 하드룰 위반 0건 (0-2-1).",
    "연차: 제욱.",
    "업로드 메모 같은 처음 보는 줄",
]


class NotesLayoutTests(unittest.TestCase):
    def test_group_saved_snapshot_lines(self):
        g = app.group_note_lines(LINES_1022)
        self.assertEqual(g["summary"][0], "밸런스(온전 출근 6명): 피로도 13~14점(차이 1), 실휴게 5~6시간(차이 1) — 가능한 최소.")
        self.assertIn("FM·유도리 모두 만족하는 표입니다: 두 기준 모두 하드룰 위반 0건 (0-2-1).", g["summary"])
        self.assertIn("연차: 제욱.", g["summary"])
        self.assertIn("업로드 메모 같은 처음 보는 줄", g["summary"])         # 모르는 줄은 숨기지 않는다
        self.assertEqual([k for k, _ in g["rotation"]], ["last_rest", "barrier", "big_rest", "patrol"])
        self.assertEqual(g["rotation"][0][1], "마지막 휴게(07시): 2 준호(이번 이전 마지막 수혜 10/04).")
        self.assertEqual(g["rule"][0], "직전 근무 07시 휴게자(4 만년)는 새 편성에서 연속 수혜 금지(16장).")
        self.assertEqual(len(g["rule"]), 3)
        self.assertTrue(g["detail"][0].startswith("피로도: 합계 82점"))
        self.assertTrue(any(x.startswith("근무자 선호(17-1)") for x in g["detail"]))
        every = " ".join([*g["summary"], *g["rule"], *g["detail"], *(x for _, x in g["rotation"])])
        self.assertNotIn("반영했습니다", every)                              # 제대로 피한 개인 회피는 적지 않음
        self.assertNotIn("과거 싸이클 영향", every)

    def test_unbalanced_points_to_detail(self):
        g = app.group_note_lines(["밸런스 판정 — 온전 출근 일반근무자 5명: 피로도 12~14점(차이 2).",
                                  "· 피로도: 아래 상위 규칙을 지키면서 계산해 보니 줄일 수 없었습니다(계산상 최소 확인)."])
        self.assertTrue(g["summary"][0].endswith("— 이유는 '밸런스 자세히'."))

    def test_saved_page_sections_pc_and_mobile(self):
        from streamlit.testing.v1 import AppTest

        from night_shift import history_store
        from tests.test_person_swap_saved import DAY, plan
        record = plan()
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                history_store.save_confirmed(Path(folder), record, "2.20", notes_snapshot=LINES_1022)
                at = AppTest.from_file(str(Path(app.__file__)), default_timeout=240)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = DAY
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                text = " ".join(m.value for m in at.markdown)
                for heading in ("📌 오늘 한눈에", "🛡 규칙 때문에 바뀐 것"):
                    self.assertIn(heading, text)
                self.assertNotIn("반영했습니다", text)
                # 2026-10-22: 순번 묶음은 이름만(설명 문장 없음), 누르면 배정 기준 + 표
                self.assertNotIn("오래 기다린 순서대로", text)
                labels = [e.label for e in at.expander]
                self.assertFalse(any("오래 기다린" in label for label in labels))
                toggle = next(t for t in at.toggle if t.label.startswith("⚖️ 밸런스 자세히"))
                self.assertNotIn("피로도: 합계 82점", text)                 # 계산 설명은 스위치 안
                toggle.set_value(True).run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertIn("피로도: 합계 82점", " ".join(m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
