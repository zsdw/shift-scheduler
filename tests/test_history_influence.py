"""과거 싸이클 기록 때문에 오늘 표에서 누군가에게 영향이 가면 특이사항에 반드시 주석 (2026-10-05 사용자 요청)."""
import unittest
from types import SimpleNamespace

from night_shift.balance_notes import history_influence_lines


def person(pid, number, fatigue, manager=False):
    return SimpleNamespace(employee_id=pid, name=f"사람{pid}", display_number=number, is_manager=manager,
                           available_time=14, fatigue_value=fatigue)


def cell(pid, slot, rest=1, kind="rest", label="휴게", install=False, remove=False):
    return SimpleNamespace(employee_id=pid, slot=SimpleNamespace(index=slot), actual_rest_time_value=rest,
                           actual_post_or_work_type=SimpleNamespace(kind=SimpleNamespace(value=kind), label=label),
                           barrier_install_flag=install, barrier_remove_flag=remove)


class HistoryInfluenceTests(unittest.TestCase):
    def setUp(self):
        self.stats = {"A": person("A", None, 10, True), "1": person("1", 1, 13), "2": person("2", 2, 15),
                      "3": person("3", 3, 15)}
        attendance = [SimpleNamespace(employee_id=p, present=True) for p in ("A", "1", "2", "3", "4", "5", "6")]
        self.record = SimpleNamespace(context=SimpleNamespace(attendance=attendance), assignments=[
            cell("1", 13, rest=0, kind="post", label="G1"), cell("2", 4, rest=0, kind="patrol", label="middle"),
            cell("3", 2, rest=0, kind="post", label="I1", install=True)])

    def test_lists_only_people_affected_today(self):
        prepared = SimpleNamespace(
            forbid_install_ids=("2",), forbid_last_rest_ids=("1",), forbid_patrol_exclusion_ids=("2",),
            previous_install_ids=(), previous_remove_ids=(), patrol_rotation_priority_ids=("2",),
            duty_rates={"barrier": {"1": 50, "2": 50, "3": 10}},
            historical_totals={"fatigue_value": {"1": 34, "2": 28, "3": 28}}, historical_nights={"1": 2, "2": 2, "3": 2})
        text = "\n".join(history_influence_lines(self.record, self.stats, prepared))
        self.assertIn("과거 싸이클 영향", text)
        self.assertIn("2 사람2: 직전 근무에서 차단봉을 설치", text)
        # 2026-10-15 순찰 보호(14-1-2)로 같은 조건의 비고 문장이 바뀜
        self.assertIn("2 사람2: 순찰 제외 후 야간·공휴일 주간 출근 2회 보호 대상이라 오늘 순찰을 맡겼습니다(14-1-2)", text)
        self.assertNotIn("18-9", text)                                     # 18-9 회전 문구 폐지(10/19) — 14-7 하층 순번
        self.assertNotIn("차단봉: 최근 3싸이클", text)                      # 15-8 횟수 기준 폐지(10/19) — 마지막 참여일 순
        self.assertIn("1 사람1: 최근 2싸이클 밤당 피로도가 평균보다 +2.0 높아", text)

    def test_nothing_for_manual_or_without_history(self):
        self.assertEqual(history_influence_lines(self.record, self.stats, None), [])
        empty = SimpleNamespace()
        self.assertEqual(history_influence_lines(self.record, self.stats, empty), [])

    def test_history_fatigue_influence_does_not_require_unique_extreme(self):
        self.stats['2'].fatigue_value = 14
        self.stats['3'].fatigue_value = 15
        self.stats['1'].fatigue_value = 14  # 오늘 동률이어도 과거 기록에 따른 보정은 설명
        prepared = SimpleNamespace(historical_totals={'fatigue_value': {'1': 36, '2': 28, '3': 28}},
                                   historical_nights={'1': 2, '2': 2, '3': 2})
        text = '\n'.join(history_influence_lines(self.record, self.stats, prepared))
        self.assertIn('1 사람1: 최근 2싸이클', text)
        self.assertNotIn('2 사람2:', text)  # 낮은 과거 피로도지만 오늘 추가 부담 없음
        self.assertIn('3 사람3: 최근 2싸이클', text)
        self.assertNotIn('가장 가벼운', text)
        self.assertNotIn('가장 무거운', text)

    def test_history_without_matching_today_effect_is_not_listed(self):
        for pid in ('1', '2', '3'):
            self.stats[pid].fatigue_value = 14
        prepared = SimpleNamespace(historical_totals={'fatigue_value': {'1': 36, '2': 28, '3': 28}},
                                   historical_nights={'1': 2, '2': 2, '3': 2})
        self.assertEqual(history_influence_lines(self.record, self.stats, prepared), [])


if __name__ == "__main__":
    unittest.main()
