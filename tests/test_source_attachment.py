"""Saved program tables show only the source label and one original-file button (PC/mobile)."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift.source_attachment import label, original, stash

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class SourceAttachmentTests(unittest.TestCase):
    def test_stash_infers_format_without_file_name(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(stash(folder, b"PK\x03\x04data", "").endswith(".xlsx"))
            self.assertTrue(stash(folder, PNG, None).endswith(".png"))
            with self.assertRaises(ValueError):
                stash(folder, b"plain", "")
        self.assertEqual(label({"source": "excel-bulk"}), "엑셀저장본")
        self.assertEqual(label({"source": "image-import"}), "이미지 저장본")

    def test_saved_night_shows_label_and_image_button_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                data = json.loads((ROOT / "history" / "2026-10-03.json").read_text(encoding="utf-8"))
                data["source"] = "image-import"
                data["source_attachment"] = stash(folder, PNG, "night.png")
                (Path(folder) / "2026-10-03.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(original(data), Path(data["source_attachment"]))
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = date(2026, 10, 3)
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                titles = [s.value for s in at.subheader] + [c.value for c in at.caption]
                self.assertTrue(any("저장된 근무표 (이미지 저장본)" in t for t in titles))
                self.assertEqual(beside_save(at), ["이미지파일 보기"])
                self.assertFalse([e.label for e in at.expander if "확인한 배정" in e.label])

    def test_saved_day_shows_label_and_image_button_beside_save(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                data = json.loads((ROOT / "history" / "day" / "2026-10-07.json").read_text(encoding="utf-8"))
                data["source"] = "image-import"   # 실제 10/7은 10/11 엑셀 일괄로 다시 저장됨 → 검사는 이미지 저장본으로 고정
                data["source_attachment"] = stash(folder, PNG, "day.png")
                (Path(folder) / "day").mkdir()
                (Path(folder) / "day" / "2026-10-07.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = date(2026, 10, 7)
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertTrue(any("주간 근무표 (이미지 저장본)" in s.value for s in at.subheader))
                self.assertEqual(beside_save(at), ["이미지파일 보기"])


def beside_save(at):
    """Original-file buttons in the same row as '💾 실제 근무 저장'."""
    def labels(node):
        out = []
        for child in getattr(node, "children", {}).values():
            if isinstance(getattr(child, "label", None), str):
                out.append(child.label)
            out += labels(child)
        return out
    columns = [labels(c) for c in at.columns]
    found = []
    for index, column in enumerate(columns):
        if "💾 실제 근무 저장" in column:
            for near in columns[max(0, index - 1):index + 2]:
                found += [label for label in near if label.endswith("보기")]
    return found


if __name__ == "__main__":
    unittest.main()
