"""업로드 = 제안, 저장본 = 확정 (2026-10-11 사용자 확정): 새 날짜만 바로 저장, 바뀐 날짜·오기·연차 충돌은 확인 필요,
한 번 처리한 원본은 다음 파일에서 무시, 직전 버전 1개 보관과 되돌리기."""
import json
import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from night_shift import upload_review as u

DAY = date(2026, 10, 10)


def plan(status, digest="d1", shift="night", reason="", record=object()):
    return N(day=DAY, shift=shift, status=status, digest=digest, reason=reason, record=record)


class TriageTests(unittest.TestCase):
    def test_classify(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(u, "leave_conflicts", return_value=[]), patch.object(u, "changes", return_value="19시 준호 I1→L3"):
            store = Path(folder)
            new, changed = plan("new"), plan("changed", "d2")
            error = plan("skip", "d3", reason="06시 원종: L3·G3 중복", record=None)
            weekend = plan("skip", "d4", reason="주말·공휴일 주간은 앱이 아직 지원하지 않습니다", record=None)
            u.triage(store, [new, changed, error, weekend])
            self.assertEqual(new.status, "new")                                 # 새 날짜는 바로 저장
            self.assertEqual((changed.status, changed.reason), ("review", "19시 준호 I1→L3"))
            self.assertEqual((error.status, error.can_apply), ("review", False))  # 오기는 기존 유지만
            self.assertEqual(weekend.status, "skip")
            self.assertEqual(u.save_pending(store, [new, changed, error, weekend], "sha", "f.xlsx"), 2)

    def test_leave_conflict_and_handled_source(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            (store / f"{DAY}.json").write_text(json.dumps({"source_hash": "saved"}), encoding="utf-8")
            with patch.object(u, "leave_conflicts", return_value=["광희 연차"]):
                p = u.triage(store, [plan("new", "x")])[0]
                self.assertEqual(p.status, "review")
                self.assertIn("광희 연차", p.reason)
                same = u.triage(store, [plan("changed", "saved")])[0]          # 그 원본으로 저장(이후 프로그램 수정) → 무시
                self.assertEqual(same.status, "same")
            u.ignore(store, DAY, "night", "kept")                               # '기존 유지'를 고른 원본 → 무시
            self.assertEqual(u.triage(store, [plan("skip", "kept", reason="오기", record=None)])[0].status, "same")


class VersionTests(unittest.TestCase):
    def test_keep_one_previous_and_revert(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            trash = store / ".trash"
            trash.mkdir()
            path = store / f"{DAY}.json"
            path.write_text(json.dumps({"v": 3, "source_hash": "new"}), encoding="utf-8")
            old1 = trash / f"{DAY}__deleted-import-20261011-100000000000.json"
            old2 = trash / f"{DAY}__deleted-import-20261011-110000000000.json"
            old1.write_text(json.dumps({"v": 1}), encoding="utf-8")
            old2.write_text(json.dumps({"v": 2, "source_hash": "old"}), encoding="utf-8")
            os.utime(old2, (time.time() - 99999, time.time() - 99999))         # 복사본 수정시각은 순서에 안 씀
            removed = []
            with patch("night_shift.kakao_sync.recycle", side_effect=lambda ps: removed.extend(ps) or len(ps)):
                u.purge_overwrite_copies(store)
                self.assertEqual(removed, [old1])                               # 직전 1개만 남김
                old1.unlink()
                self.assertEqual(u.previous(store, DAY, "night"), old2)
                u.revert(store, DAY, "night")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["v"], 2)
                self.assertTrue(u.handled(store, DAY, "night", "new"))         # 되돌린 원본은 다음 업로드에서 무시
                u.revert(store, DAY, "night")                                    # 다시 누르면 원래대로
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["v"], 3)


class NameFixKeepTests(unittest.TestCase):
    def test_name_fix_survives_unchanged_source(self):
        """명령서 번호 이름 고침: 원본 명단이 그대로면 다음 업로드에도 유지, 원본이 바뀌면 버림."""
        from night_shift import order_source
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            names = {"1": "광희", "2": "광희"}
            first = {"2026-10-07": {"day": {"names": names}}, "2026-10-08": {"day": {"names": {"6": "만년"}}}}
            order_source.publish_uploaded(store, b"x", "a.xlsx", first)
            order_source.save_name_fix(store, date(2026, 10, 7), "day", {"1": "준형"})
            order_source.save_name_fix(store, date(2026, 10, 8), "day", {"6": "여진"})
            second = {"2026-10-07": {"day": {"names": names}}, "2026-10-08": {"day": {"names": {"6": "광희"}}}}
            order_source.publish_uploaded(store, b"y", "b.xlsx", second)
            self.assertEqual(order_source.load_name_fixes(store), {"2026-10-07": {"day": {"1": "준형"}}})


if __name__ == "__main__":
    unittest.main()
