"""지난 근무표 '포스트별 실제 운영 수정': 같은 포스트에 다시 적용하면 겹치는 시간은 마지막 적용이 덮어쓴다
(2026-10-02 사용자 확정). 예: I1 00~04시 휴게성 → I1 00~03시 휴게성이면 04시는 원래 계획대로."""
import unittest

from night_shift.actual_edit import add_state_edit


def cells(edits, post):
    """각 슬롯에서 마지막으로 적용되는 운영 (apply_edits와 같은 순서)."""
    out = {}
    for e in edits:
        state = e.get("posts", {}).get(post)
        if e.get("type") == "state" and state:
            for t in range(min(e["from"], e["to"]), max(e["from"], e["to"]) + 1):
                out[t] = state
    return out


class LatestStateEditWinsTests(unittest.TestCase):
    def test_narrower_range_replaces_overlap(self):
        edits = add_state_edit([], "I1", 6, 10, "rest")             # 00~04시
        edits = add_state_edit(edits, "I1", 6, 9, "rest")           # 다시 00~03시
        self.assertEqual(cells(edits, "I1"), {6: "rest", 7: "rest", 8: "rest", 9: "rest"})
        self.assertEqual(len(edits), 1)                             # 앞의 00~04시는 남지 않음

    def test_overlapping_old_range_is_replaced_whole(self):
        edits = add_state_edit([], "I1", 4, 10, "rest")             # 22~04시
        edits = add_state_edit(edits, "I1", 6, 9, "seated")         # 다시 00~03시 좌식 → 이게 I1의 규칙
        self.assertEqual(cells(edits, "I1"), {t: "seated" for t in range(6, 10)})

    def test_separate_ranges_are_kept(self):
        edits = add_state_edit([], "I1", 4, 5, "rest")              # 22~23시
        edits = add_state_edit(edits, "I1", 6, 9, "rest")           # 00~03시 (겹치지 않음)
        self.assertEqual(cells(edits, "I1"), {t: "rest" for t in range(4, 10)})
        self.assertEqual(len(edits), 2)

    def test_other_posts_and_other_edits_untouched(self):
        swap = {"type": "swap", "a": ["1", 3], "b": ["2", 3]}
        mixed = {"type": "state", "from": 6, "to": 10, "posts": {"I1": "rest", "G1": "seated"}}
        edits = add_state_edit([swap, mixed], "I1", 6, 9, "rest")
        self.assertIn(swap, edits)
        self.assertEqual(cells(edits, "G1"), {t: "seated" for t in range(6, 11)})
        self.assertEqual(cells(edits, "I1"), {t: "rest" for t in range(6, 10)})


if __name__ == "__main__":
    unittest.main()
