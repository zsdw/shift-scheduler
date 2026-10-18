"""야간 '이력 입력' 칸 없음 — 항상 저장된 실제 이력, 반영 날짜는 '생성 상세 설정' 안 (2026-10-08, PC·폰)."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


class HistoryDefaultTests(unittest.TestCase):
    def test_no_history_input_section_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
                at.query_params["view"] = view
                at.session_state["shift_date"] = date(2026, 10, 9)
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertFalse([s for s in at.subheader if s.value == "이력 입력"])
                self.assertFalse([r for r in at.radio if r.label == "과거 이력"])
                self.assertTrue(any("이력 없이 생성" in c.value or "실제 근무 이력 반영" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
