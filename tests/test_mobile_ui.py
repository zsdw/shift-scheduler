"""폰 화면 (2026-10-02 사용자 요청): 폰으로 접속하면 사이드바 없이 본문 맨 위 '근무 조건' 칸 → 생성 →
근무표(전체 표 / 사람별) → 확정. 컴퓨터 화면은 그대로. 주소 ?view=mobile 로 폰 화면을 강제할 수 있다."""
import os
import tempfile

os.environ["NIGHT_SHIFT_HISTORY_DIR"] = tempfile.mkdtemp(prefix="night_shift_history_mobile_")

import unittest
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

import app
from night_shift.models import Mode, NightType
from night_shift.service import ShiftRequest, SolveOptions, run_schedule

APP = str(Path(__file__).resolve().parents[1] / "app.py")

# 검사 시간 단축(2026-10-13): 여러 검사가 같은 날짜·같은 조건의 첫 야간 근무표(약 1분)를 각자 새로 만들던 것을
# 한 번만 계산하고 사본을 돌려준다. 재생성(다른 표 제외 조건)·긴급 재편성은 매번 실제로 계산한다. 앱 코드는 그대로.
import copy
import night_shift.service as _service
_real_run_schedule = _service.run_schedule
_first_runs = {}


def _cached_run_schedule(request, history=None, options=None, *args, **kwargs):
    if args or kwargs or options is None or options.exclude_assignments:
        return _real_run_schedule(request, history, options, *args, **kwargs)
    key = (repr(request), repr(history), repr(options))
    if key not in _first_runs:
        _first_runs[key] = _real_run_schedule(request, history, options)
    return copy.deepcopy(_first_runs[key])


_service.run_schedule = _cached_run_schedule
# 앱은 표시 번호를 random.SystemRandom으로 섞는다(app.random_display_numbers). 이 검사 프로세스에서만 고정해
# 검사마다 같은 번호 배치 → 같은 조건 → 위 재사용이 맞도록 한다.
import random as _random
_random.SystemRandom = lambda *a, **k: _random.Random(20261013)


def mobile_app(day: date) -> AppTest:
    at =AppTest.from_file(APP, default_timeout=300)   # 야간 생성(계산 단계 증가)이 동시 실행 중에도 끝나도록
    at.query_params["view"] = "mobile"
    at.run()
    at.session_state["shift_date"] = day
    at.run()
    return at


class MobileViewTests(unittest.TestCase):
    def test_mobile_generate_confirm_and_saved_view(self):
        at = mobile_app(date(2026, 9, 28))
        self.assertFalse(at.exception)
        self.assertEqual(len(at.sidebar.children), 0)                  # 사이드바 없음
        self.assertIn("⚙️ 근무 조건 · 생성", [e.label for e in at.expander])
        self.assertEqual(len(at.metric), 0)                            # 큰 숫자 5개 대신 한 줄 요약
        self.assertTrue(any("v2.21" in c.value for c in at.caption))
        at.button(key="generate_button").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state["last_result"].valid)
        self.assertIn("직원 분석", [t.label for t in at.tabs])
        self.assertIn("직원 상세분석", [t.label for t in at.tabs])
        self.assertNotIn("👤 사람별", [t.label for t in at.tabs])
        self.assertEqual(len(at.metric), 0)
        self.assertTrue(any("staff-stats" in m.value for m in at.markdown))
        self.assertNotIn("큰 표 · 자세한 메모", [e.label for e in at.expander])
        self.assertTrue(at.get("download_button"))
        previous = at.session_state["last_result"]
        at.button(key="regenerate_0").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["schedule_results"]), 2)
        self.assertIs(at.session_state["schedule_results"][0], previous)
        self.assertTrue(at.session_state["last_result"].valid)
        self.assertNotEqual(previous.record.assignments, at.session_state["last_result"].record.assignments)
        self.assertFalse(app.history_store_exists(date(2026, 9, 28)))
        at.button(key="confirm_1").click().run()                      # 폰에서도 확정 저장
        self.assertFalse(at.exception)
        self.assertTrue(any("확정 저장" in s.value for s in at.success))
        self.assertIn("saved_tap_mode_2026-09-28", [r.key for r in at.radio])   # 폰도 PC와 같은 저장본 수정 화면
        self.assertIn("saved_save_2026-09-28", [b.key for b in at.button])
        self.assertIn("saved_delete_2026-09-28", [b.key for b in at.button])
        at.button(key="saved_delete_2026-09-28").click().run()
        self.assertTrue(app.history_store_exists(date(2026, 9, 28)))
        at.button(key="saved_delete_no_2026-09-28").click().run()
        self.assertTrue(app.history_store_exists(date(2026, 9, 28)))
        at.button(key="saved_delete_2026-09-28").click().run()
        at.button(key="saved_delete_yes_2026-09-28").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(app.history_store_exists(date(2026, 9, 28)))

    def test_day_regenerate_button_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view):
                at = AppTest.from_file(APP, default_timeout=120)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = date(2026, 10, 1)
                at.run()
                at.button(key="day_generate").click().run()
                self.assertFalse(at.exception)
                at.button(key="gen_regenerate_base_0").click().run()
                self.assertFalse(at.exception)
                self.assertIn("gen_confirm_base_1", [b.key for b in at.button])
                from history_ui import day_store_dir
                self.assertFalse(app._history_store.exists(day_store_dir(), date(2026, 10, 1)))

    def test_mobile_status_select_and_manager_lock(self):
        from unittest.mock import patch
        at = mobile_app(date(2026, 9, 28))
        event = {"employee": "1", "status": app.NIGHT_STATUSES[1], "nonce": "test-1"}
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__",
                   autospec=True, side_effect=lambda component, **kwargs: event if component.name.endswith("night_roster_picker") else None):
            at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["night_statuses"]["1"], app.NIGHT_STATUSES[1])
        at.radio(key="manager_state").set_value("A 결근 (준호 대행)").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["night_statuses"]["6"], app.NIGHT_STATUSES[0])

    def test_mobile_day_status_select_uses_roster_picker(self):
        # 2026-10-03: 폰 주간 근무자도 야간처럼 상태 칸을 눌러 고르는 선택표 → 생성에 반영
        from unittest.mock import patch
        from night_shift.day_shift import DEFAULT_ROSTER
        day, name = date(2026, 10, 1), DEFAULT_ROSTER[1]
        at = mobile_app(day)
        event = {"employee": name, "status": "오전반차", "nonce": "day-test-1"}
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__",
                   autospec=True, side_effect=lambda component, **kwargs: event if component.name.endswith("day_roster_picker") else None):
            at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state[f"day_statuses_{day}"][name], "오전반차")
        self.assertIn("명단 수정 (이름 추가·삭제)", [e.label for e in at.expander])
        at.button(key="day_generate").click().run()
        self.assertFalse(at.exception)
        schedule = at.session_state["day_results"][0]
        self.assertEqual(next(p.status for p in schedule.people if p.name == name), "오전반차")

    def test_mobile_day_emergency_form_reoptimizes_with_lock(self):
        # 2026-10-03: 폰에서도 긴급 반차·이탈 (몇 시까지 LOCK → 누가 → 종류 → 재편성). PC와 같은 reoptimize_day
        at = mobile_app(date(2026, 10, 1))
        at.button(key="day_generate").click().run()
        self.assertFalse(at.exception)
        self.assertIn("🚨 긴급 반차·이탈 재편성", [e.label for e in at.expander])   # 2026-10-05: 접힌 칸 안
        at.selectbox(key="m_lock_gen_base_0").set_value(2).run()          # 10시까지 LOCK → 11시부터 재편성
        at.radio(key="m_kind_gen_base_0").set_value("leave").run()
        at.button(key="m_rebalance_gen_base_0").click().run()
        self.assertFalse(at.exception)
        emergencies = at.session_state["day_emergencies"]
        self.assertEqual(len(emergencies), 1)
        base, schedule = at.session_state["day_results"][0], emergencies[0]
        self.assertEqual(schedule.emergency["start"], 3)
        for pid, row in base.grid.items():                                 # LOCK 이전은 그대로
            self.assertEqual(schedule.grid[pid][:3], row[:3])

    def test_mobile_night_emergency_form_adds_rebalanced_candidate(self):
        at = mobile_app(date(2026, 9, 28))
        at.button(key="generate_button").click().run()
        self.assertFalse(at.exception)
        self.assertIn("🚨 긴급 반차·이탈 재편성", [e.label for e in at.expander])   # 2026-10-05: 접힌 칸 안
        # PC test_rebalance_ui와 같은 조건: 18시까지 LOCK → 1번 직원 후반부 반차
        at.selectbox(key="m_night_lock_0").set_value(0).run()
        at.selectbox(key="m_night_pid_0").set_value("1").run()
        at.radio(key="m_night_kind_0").set_value("half").run()
        at.button(key="m_night_rebalance_0").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        results = at.session_state["schedule_results"]
        self.assertEqual(len(results), 2)
        info = results[1].rebalance_info
        self.assertEqual((info.reoptimization_start_index, info.unavailable_employee_id, info.unavailable_from_index),
                         (1, "1", 7))
        self.assertTrue(results[1].valid)

    def test_saved_night_emergency_rebalance_pc_and_mobile(self):
        # 2026-10-03: 저장된 야간 기록에서도 긴급 반차 (18시까지 LOCK, 1번 후반부 반차 — PC 재편성 테스트와 같은 조건) → 확정 시 덮어쓰기 확인
        from night_shift import history_store
        from history_ui import store_dir
        for view, day in (("pc", date(2026, 10, 9)), ("mobile", date(2026, 10, 10))):   # A조 야간 날짜
            with self.subTest(view=view):
                staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
                from night_shift.calendar_info import night_type_for
                base = run_schedule(ShiftRequest(day, NightType(night_type_for(day)), Mode.FM, staff), None,
                                    SolveOptions(rules_version="2.20", seconds=15))
                self.assertTrue(base.valid)
                history_store.save_confirmed(store_dir(), base.record, "2.20")
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = day
                at.run()
                self.assertFalse(at.exception)
                self.assertIn("🚨 긴급 반차·이탈 재편성", [e.label for e in at.expander])   # 접힌 칸 (2026-10-05)
                at.selectbox(key=f"saved_lock_{day}").set_value(0).run()          # 18시까지 LOCK
                at.selectbox(key=f"saved_pid_{day}").set_value("1").run()
                at.radio(key=f"saved_kind_{day}").set_value("half").run()
                at.button(key=f"saved_rebalance_go_{day}").click().run()
                self.assertFalse(at.exception)
                self.assertFalse(at.error, [e.value for e in at.error])
                outcome = at.session_state[f"saved_rebalance_{day}_{base.record.record_id}"]
                self.assertTrue(outcome.valid)
                self.assertEqual((outcome.rebalance_info.reoptimization_start_index,
                                  outcome.rebalance_info.unavailable_from_index), (1, 7))
                locked = {(r.employee_id, r.slot.index): r.displayed_assignment for r in base.record.assignments
                          if r.slot.index < 1}
                self.assertEqual(locked, {(r.employee_id, r.slot.index): r.displayed_assignment
                                          for r in outcome.record.assignments if r.slot.index < 1})
                self.assertEqual(history_store.load(store_dir(), day)["plan_record"].record_id, base.record.record_id)
                key = f"saved_rebalance_confirm_{day}"
                at.button(key=key).click().run()                                  # 이미 저장본 있음 → 확인 먼저
                self.assertEqual(history_store.load(store_dir(), day)["plan_record"].record_id, base.record.record_id)
                at.button(key=f"{key}_overwrite").click().run()
                self.assertFalse(at.exception)
                saved = history_store.load(store_dir(), day)
                self.assertEqual(saved["plan_record"].record_id, outcome.record.record_id)
                self.assertEqual(history_store.locked_through(saved), 0)

    def test_mobile_has_pc_tools_import_and_trash(self):
        # 2026-10-03: PC 기능 전부 폰에서도 — 이력 가져오기·휴지통
        at = mobile_app(date(2026, 9, 28))
        self.assertFalse(at.exception)
        labels = [e.label for e in at.expander]
        self.assertIn("📥 파일 업로드 · 현장 양식 다운로드 · 최종 실제 근무표 저장", labels)
        self.assertTrue(any(label.startswith("🗑 휴지통") for label in labels))

    def test_mobile_generated_grid_tap_swap(self):
        # 폰 생성표: 토글 없이 항상 교환·LOCK 표를 표시한다. 교환 요청은 PC와 같은 검증을 거친다.
        from unittest.mock import patch
        at = mobile_app(date(2026, 9, 28))
        at.button(key="generate_button").click().run()
        self.assertFalse(at.exception)
        calls = []
        result = at.session_state["schedule_results"][0]
        a, b = (sorted({r.employee_id for r in result.record.assignments} - {"A"}))[:2]
        event = {"kind": "person", "source": a, "target": b, "nonce": "tap-1"}

        def fake(component, **kwargs):
            if component.name.endswith("drag_schedule"):
                calls.append(kwargs["data"])
                return event
            return None
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True, side_effect=fake):
            at.run()
        self.assertFalse(at.exception)
        self.assertTrue(calls and calls[0]["tap_swap"])
        changed = at.session_state["schedule_results"][0]
        self.assertTrue(changed is not result or at.error)          # 교환되었거나 규칙 위반 이유 표시

    def test_mobile_saved_editor_tap_swap_records_edit(self):
        from unittest.mock import patch
        from night_shift import history_store
        from history_ui import store_dir
        day = date(2026, 10, 4)
        staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
        from night_shift.calendar_info import night_type_for
        base = run_schedule(ShiftRequest(day, NightType(night_type_for(day)), Mode.FM, staff), None,
                            SolveOptions(rules_version="2.20", seconds=15))
        history_store.save_confirmed(store_dir(), base.record, "2.20")
        at = mobile_app(day)
        at.radio(key=f"saved_tap_mode_{day}").set_value("실제 근무 교환").run()
        rows = {(r.employee_id, r.slot.index): r for r in base.record.assignments}
        ids = sorted({p for p, _ in rows} - {"A"})
        t = next(t for t in range(14) if rows[(ids[0], t)].displayed_assignment != rows[(ids[1], t)].displayed_assignment)
        calls = []
        event = {"kind": "cell", "source": [ids[0], t], "target": [ids[1], t], "nonce": "saved-tap-1"}

        def fake(component, **kwargs):
            if component.name.endswith("drag_schedule") and kwargs.get("key") == f"saved_grid_{day}":
                calls.append(kwargs["data"])
                return event
            return None
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True, side_effect=fake):
            at.run()
        self.assertFalse(at.exception)
        self.assertTrue(calls[0]["tap_swap"])
        self.assertFalse(calls[0]["cell_click"])
        edits = at.session_state[f"saved_edits_{day}_{history_store.load(store_dir(), day)['confirmed_at']}"]
        self.assertEqual(edits[-1], {"type": "swap", "a": [ids[0], t], "b": [ids[1], t]})
        at.button(key=f"saved_save_{day}").click().run()
        self.assertEqual(history_store.load(store_dir(), day)["edits"][-1]["type"], "swap")

    def test_mobile_day_emergency_can_be_dropped(self):
        at = mobile_app(date(2026, 10, 1))
        at.button(key="day_generate").click().run()
        at.selectbox(key="m_lock_gen_base_0").set_value(2).run()
        at.radio(key="m_kind_gen_base_0").set_value("leave").run()
        at.button(key="m_rebalance_gen_base_0").click().run()
        self.assertEqual(len(at.session_state["day_emergencies"]), 1)
        at.button(key="gen_drop_0").click().run()                          # 폰에서도 재편성 버리기
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["day_emergencies"]), 0)

    def test_saved_grid_hour_click_locks_and_name_rebalances(self):
        # 2026-10-03: 저장본 표에서도 시간 칸 누르기 → 그 시간까지 LOCK 빗금 → 이름 누르기 → 반차·이탈 재편성 (PC·폰)
        from night_shift import history_store
        from history_ui import store_dir
        from night_shift.calendar_info import night_type_for
        for view, day in (("pc", date(2026, 10, 15)), ("mobile", date(2026, 10, 16))):
            with self.subTest(view=view):
                staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
                base = run_schedule(ShiftRequest(day, NightType(night_type_for(day)), Mode.FM, staff), None,
                                    SolveOptions(rules_version="2.20", seconds=15))
                history_store.save_confirmed(store_dir(), base.record, "2.20")
                at = AppTest.from_file(APP, default_timeout=180)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = day
                at.run()
                at.session_state[f"saved_leave_request_{day}"] = {"kind": "lockhour", "t": 2}
                at.run()
                self.assertEqual(at.session_state[f"saved_leave_lock_{day}"], 2)        # 20시까지 빗금
                at.session_state[f"saved_leave_request_{day}"] = {"kind": "leave", "pid": "6", "choice": "half"}
                at.run()
                self.assertFalse(at.exception)
                self.assertIsNone(at.session_state[f"saved_leave_lock_{day}"])           # 요청 뒤 LOCK 선택 해제
                key = f"saved_rebalance_{day}_{base.record.record_id}"
                if key in at.session_state:                                              # 재편성표가 생김
                    outcome = at.session_state[key]
                    self.assertTrue(outcome.valid)
                    info = outcome.rebalance_info
                    self.assertEqual((info.locked_through_index, info.unavailable_employee_id,
                                      info.unavailable_from_index), (2, "6", 7))
                else:                                                                    # 해가 없으면 이유 표시
                    self.assertTrue(at.error, "재편성표도 안내도 없음")

    def test_mobile_day_delete_cancel_and_trash(self):
        from tests.test_day_shift import people
        from night_shift.day_shift import solve_day, save_day
        from history_ui import day_store_dir
        day = date(2026, 10, 7)
        schedule, status = solve_day(day, people(), seconds=20)
        self.assertIsNotNone(schedule, status)
        save_day(day_store_dir(), schedule)
        at = mobile_app(day)
        self.assertFalse(at.exception)
        at.button(key=f"day_delete_{day}").click().run()
        self.assertTrue(app._history_store.exists(day_store_dir(), day))
        at.button(key=f"day_delete_no_{day}").click().run()
        self.assertTrue(app._history_store.exists(day_store_dir(), day))
        at.button(key=f"day_delete_{day}").click().run()
        at.button(key=f"day_delete_yes_{day}").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(app._history_store.exists(day_store_dir(), day))
        self.assertTrue(app._history_store.list_trash(day_store_dir()))

    def test_desktop_keeps_sidebar(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.session_state["shift_date"] = date(2026, 9, 28)
        at.run()
        self.assertFalse(at.exception)
        self.assertGreater(len(at.sidebar.children), 0)
        self.assertEqual(len(at.metric), 5)

    def test_person_and_compact_html(self):
        staff = app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})
        result = run_schedule(ShiftRequest(date(2026, 10, 5), NightType.N1, Mode.FM, staff), None,
                              SolveOptions(rules_version="2.20", seconds=15))
        self.assertTrue(result.valid)
        person = app.person_schedule_html(result, "1")
        self.assertEqual(person.count("<tr>"), 14)                     # 18시~07시 14칸
        self.assertIn("18시", person)
        self.assertIn("07시", person)
        self.assertEqual(person.count("<td"), 42)                    # 시간 / 포스트 / 실제 상태
        self.assertIn("border-left:1px", person)
        self.assertIn("입식", person)
        self.assertIn("좌식", person)
        self.assertIn("휴게성", person)
        compact = app.schedule_html(result, compact=True)
        from html.parser import HTMLParser

        class Table(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows, self.current = [], None

            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.current = []
                    self.rows.append(self.current)
                elif tag in ("td", "th"):
                    self.current.append("")

            def handle_data(self, data):
                if self.current:
                    self.current[-1] += data

        table = Table()
        table.feed(compact)
        self.assertEqual(len(table.rows), 15)                         # 전 시간 한 표
        self.assertEqual([r[0] for r in table.rows[1:]],
                         [f"{h:02d}" for h in (*range(18, 24), *range(8))])
        self.assertTrue(all(len(r) == 1 + len(result.employee_stats) for r in table.rows))
        self.assertNotIn("min-width", compact)                       # 화면 밖으로 밀리지 않음
        self.assertNotIn("overflow-x", compact)
        self.assertIn("↑", compact)                                  # 차단봉 담당 표시
        self.assertIn("↓", compact)
        self.assertIn("실제 보안실 대기", compact)                    # 상세 메모 보존
        for person in result.employee_stats.values():
            self.assertIn(person.name, compact)


if __name__ == "__main__":
    unittest.main()

