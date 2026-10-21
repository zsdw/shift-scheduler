"""Streamlit UI: confirmed history, actual-shift corrections and comparison."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from html import escape
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from night_shift import history_store
from night_shift.models import barrier_history_counts
from night_shift.actual_edit import (actual_checks, add_state_edit, apply_edits, cell_notes, changed_cells,
                                    describe_edit)
from night_shift.schedule_edit import record_grid_payload
from night_shift.service import calculate_all_stats

def store_dir() -> Path:
    """History folder; NIGHT_SHIFT_HISTORY_DIR overrides it (tests use a temp dir)."""
    override = os.environ.get("NIGHT_SHIFT_HISTORY_DIR")
    return Path(override) if override else Path(__file__).resolve().parent / "history"


def upload_saved_label(data: dict) -> str:
    """주간·야간 파일 저장 출처를 같은 문구로 표시한다(기존 저장본도 지원)."""
    if not str(data.get('source', '')).startswith(('excel', 'image')):
        return ''
    name = data.get('source_file', '')
    if not name:
        match = re.search(r'(?:가져온 파일|엑셀 편성표 일괄 가져오기):\s*([^\n]+)', data.get('note', ''))
        name = match.group(1).split(' / ')[0].strip() if match else ''
    label = '📥 업로드 파일로 최종 실제 근무표 저장됨' + (f' · {name}' if name else '')
    if data.get('final_save_method') == 'screen-edit' or data.get('edited_at'):
        label += ' · 이후 화면 수정 반영'
    return label
HOURS = [f"{(18 + t) % 24:02d}시" for t in range(14)]
STAT_COLUMNS = (("fatigue_value", "피로도"), ("actual_work_time_value", "실근무"),
                ("actual_rest_time_value", "실휴게"), ("post_standing", "입식"), ("post_seated", "좌식"),
                ("patrol_count", "순찰"), ("max_rule_work_run", "최장 연속근무"))


def stored_before(shift_date: date) -> list[date]:
    return [d for d in history_store.list_dates(store_dir()) if d < shift_date]


def history_caption(shift_date: date) -> str:
    dates = sorted(stored_before(shift_date), reverse=True)[:4]
    if not dates:
        return "저장된 확정 근무표가 없습니다."
    weights = history_store.cycle_weights(len(dates))
    parts = [f"{d.strftime('%m/%d')} {w * 100:.0f}%" for d, w in zip(dates, weights)]
    return "실제 근무 이력 반영: " + ", ".join(parts) + " (최근 4근무 똑같은 비중)"


def confirm_button(result, key: str, notes=None) -> None:
    """'이 근무표로 확정' for a valid generated schedule.
    notes: 화면에 보인 특이사항 문장 목록을 돌려주는 함수(2026-10-20, 확정 당시 문장 스냅샷)."""
    def snapshot():
        try:
            return notes() if callable(notes) else notes
        except Exception:
            return None
    if result is None or not result.valid:
        return
    shift_date = result.context.shift_start_date
    already = history_store.exists(store_dir(), shift_date)
    if st.session_state.get(f"{key}_ask_overwrite"):
        st.warning(f"{shift_date} 근무표가 이미 저장되어 있습니다. 덮어쓰면 기존 저장본(수정본 포함)은 휴지통으로 옮겨집니다.")
        c1, c2 = st.columns(2)
        if c1.button("덮어쓰고 확정", key=f"{key}_overwrite"):
            if history_store.exists(store_dir(), shift_date):
                history_store.delete_to_trash(store_dir(), shift_date)
            history_store.save_confirmed(store_dir(), result.record, result.rules_version,
                                         rebalance=result.rebalance_info, notes_snapshot=snapshot())
            st.session_state[f"{key}_ask_overwrite"] = False
            st.session_state["flash"] = f"{shift_date} 근무표를 확정 저장했습니다."
            st.rerun()
        if c2.button("취소", key=f"{key}_cancel"):
            st.session_state[f"{key}_ask_overwrite"] = False
            st.rerun()
        return
    if st.button("✅ 이 근무표로 확정", key=key, type="primary"):
        if already:
            st.session_state[f"{key}_ask_overwrite"] = True
            st.rerun()
        history_store.save_confirmed(store_dir(), result.record, result.rules_version,
                                     rebalance=result.rebalance_info, notes_snapshot=snapshot())
        st.session_state["flash"] = f"{shift_date} 근무표를 확정 저장했습니다. 이후 근무표는 이 날의 실제근무를 이력으로 참고합니다."
        st.rerun()
    elif already:
        st.caption(f"{shift_date} 근무표는 이미 확정 저장되어 있습니다.")


def _stats_frame(record) -> pd.DataFrame:
    stats = sorted(calculate_all_stats(record).values(),
                   key=lambda p: (not p.is_manager, p.display_number or 0))
    return pd.DataFrame([{"직원": ("통제" if p.is_manager and p.display_number is None
                                   else f"{p.display_number} {p.name}"),
                          **{label: getattr(p, key) for key, label in STAT_COLUMNS}} for p in stats])


def _checks_frame(record) -> pd.DataFrame:
    rows = actual_checks(record)
    return pd.DataFrame(rows).rename(columns={"rule": "규칙", "person": "직원", "time": "시간", "detail": "내용"}) \
        if rows else pd.DataFrame(columns=["규칙", "직원", "시간", "내용"])


def day_store_dir() -> Path:
    """주간 근무표 저장 폴더 (야간과 분리)."""
    return store_dir() / "day"


def render_trash(prefix: str) -> None:
    stores = ((store_dir(), "야간"), (day_store_dir(), "주간"),
              (day_store_dir().parent / "weekend_day", "주말 주간"))   # 주말 주간 삭제도 같은 휴지통 (2026-10-18)
    items = [(store, kind, item) for store, kind in stores for item in history_store.list_trash(store)]
    with st.expander(f"🗑 휴지통 ({len(items)})"):
        if not items:
            st.caption("삭제한 근무표가 없습니다.")
        for store, kind, item in items:
            c1, c2 = st.columns([3, 2])
            c1.write(f"{item['date']} {kind}  \n삭제 {item['deleted'][:8]} {item['deleted'][9:11]}:{item['deleted'][11:13]}")
            if c2.button("복구", key=f"{prefix}_restore_{kind}_{item['name']}"):
                try:
                    day = history_store.restore_from_trash(store, item["name"])
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success(f"{day} {kind} 근무표를 복구했습니다.")
                    st.rerun()
        if items:
            ask = f"{prefix}_ask_empty_trash"
            if st.session_state.get(ask):
                st.warning(f"휴지통의 근무표 {len(items)}개를 완전히 삭제합니다. 되돌릴 수 없습니다.")
                c1, c2 = st.columns(2)
                if c1.button("완전 삭제", key=f"{prefix}_empty_yes", type="primary"):
                    for store, _ in stores:
                        history_store.empty_trash(store)
                    st.session_state[ask] = False
                    st.rerun()
                if c2.button("취소", key=f"{prefix}_empty_no"):
                    st.session_state[ask] = False
                    st.rerun()
            elif st.button("휴지통 비우기", key=f"{prefix}_empty_trash"):
                st.session_state[ask] = True
                st.rerun()


def saved_dates_caption() -> str:
    dates = history_store.list_dates(store_dir())
    if not dates:
        return "저장된 근무표가 없습니다."
    return "저장된 근무표: " + ", ".join(d.strftime("%m/%d") for d in dates[-10:])


EMERGENCY_BOXES: dict = {}                  # 이번 실행에서 만든 긴급 반차 접힌 칸 (폰 입력칸을 그 안에 넣음)


def emergency_toggle(key: str, force: bool = False, lock_key: str | None = None) -> bool:
    """긴급 반차·이탈 재편성은 '🧭 앞으로의 편성 방향'처럼 접힌 칸(>)을 눌러야 보인다 (2026-10-05 사용자 요청).
    칸 안: '표의 시간 칸을 눌러 LOCK하기' 스위치(켜야 파란 안내·시간 칸 LOCK) + 폰 입력칸(emergency_box).
    야간·주간, 생성표·저장본, PC·폰 공통. force: LOCK을 고르는 중이면 펼치고 켠 상태로 둔다."""
    box = st.expander("🚨 긴급 반차·이탈 재편성", expanded=bool(force))
    EMERGENCY_BOXES[key] = box
    def cancel_lock():                       # 끄면 고른 LOCK을 취소하고 아무 일 없던 상태로 (2026-10-05 사용자 요청)
        if not st.session_state.get(key) and lock_key:
            st.session_state[lock_key] = None
    with box:
        if force:
            st.session_state[key] = True
        return st.toggle("표의 시간 칸을 눌러 LOCK하기", key=key, on_change=cancel_lock,
                         help="켜면 표의 시간 칸을 눌러 LOCK하고 빠지는 사람(이름)을 골라 남은 시간을 다시 편성합니다. "
                              "끄면 고른 LOCK이 취소됩니다.")


def emergency_box(key: str):
    """emergency_toggle이 만든 접힌 칸 (없으면 새 접힌 칸)."""
    return EMERGENCY_BOXES.get(key) or st.expander("🚨 긴급 반차·이탈 재편성", expanded=False)


def _hints(items, small: bool = False) -> None:
    size = "padding:0 6px;margin:0 3px 3px 0;font-size:.66rem" if small else "padding:1px 9px;margin:0 6px 4px 0;font-size:.78rem"
    chips = "".join(f"<span style='display:inline-block;background:#F1F5F9;border:1px solid #E2E8F0;"
                    f"border-radius:999px;{size};color:#334155'>{i}</span>"
                    for i in items)
    # 칩이 아래 표(iframe)와 겹치지 않게 아래 여백 확보 (2026-10-05)
    st.markdown(f"<div style='padding-bottom:14px;line-height:1.6'>{chips}</div>", unsafe_allow_html=True)


def saved_status(prefix: str, day: date) -> dict:
    """State of a saved night for the status badge (read before the editor renders)."""
    if not history_store.exists(store_dir(), day):
        return {}
    data = history_store.load(store_dir(), day)
    edits = st.session_state.get(f"{prefix}_edits_{day}_{data['confirmed_at']}", data["edits"])
    return {"has_revision": bool(data["edits"]), "unsaved": edits != data["edits"],
            "locked": history_store.locked_through(data) >= 0}


def _md(text: str) -> str:
    """Streamlit markdown treats ~ as strikethrough; keep time ranges literal."""
    return str(text).replace("~", "\\~")


def _toggle_applies(record) -> bool:
    """FM·유도리 보기 버튼은 FM으로 만든 표에만 (유도리로 만든 표·도중 유도리 전환 표는 이미 유도리 표시)."""
    from night_shift.models import Mode
    return record.context.effective_mode == Mode.FM and record.context.flexible_from_slot is None


def view_mode(key: str, record) -> str:
    return st.session_state.get(key, "FM") if _toggle_applies(record) else "FM"


def view_toggle(payload: dict, record, key: str) -> str:
    """표 제목 줄의 FM·유도리 보기 버튼 (2026-10-13 사용자 요청). 처음엔 FM, 유도리를 누르면 유도리 적용
    시간대·포스트(기본값 I1 22~03시 등)를 자홍색 테두리로 보여 준다. 배정·교환은 FM 표 그대로."""
    if not _toggle_applies(record):
        return "FM"
    mode = view_mode(key, record)
    payload["view_toggle"], payload["view_mode"] = True, mode
    if mode == "유도리":
        from night_shift.service import flexible_view
        from night_shift.schedule_edit import sheet_meta
        from night_shift.presentation import flexible_band
        flex = flexible_view(record)
        if payload.get("sheet"):
            payload["sheet"]["operations"] = sheet_meta(flex.context)["operations"]
        payload["band"] = flexible_band(flex.context)
    return mode


def handle_view_event(event, key: str) -> bool:
    """표에서 FM·유도리 버튼을 누른 이벤트면 보기만 바꾸고 True."""
    if not (isinstance(event, dict) and event.get("kind") == "view"):
        return False
    if event.get("nonce") != st.session_state.get(key + "_nonce"):
        st.session_state[key + "_nonce"] = event.get("nonce")
        st.session_state[key] = "유도리" if event.get("mode") == "유도리" else "FM"
        st.rerun()
    return True


def view_record(record, key: str):
    """분석(전체 비교·직원 상세분석)용 기록: 유도리 보기면 같은 배정을 유도리로 다시 계산한 표."""
    if record is not None and view_mode(key, record) == "유도리":
        from night_shift.service import flexible_view
        return flexible_view(record)
    return record


def _summary_tabs(prefix: str, record, summary_table, summary_detail, baseline_record=None, view_key=None) -> None:
    if summary_table is None or summary_detail is None:
        return
    if view_key and view_mode(view_key, record) == "유도리":
        st.caption("🟣 유도리 기준으로 다시 계산한 값입니다(배정은 같음, 유도리 적용 칸은 휴게성·좌식 회계).")
        record, baseline_record = view_record(record, view_key), view_record(baseline_record, view_key)
    view = SimpleNamespace(employee_stats=calculate_all_stats(record), record=record)
    baseline = (calculate_all_stats(baseline_record)
                if baseline_record is not None and baseline_record.assignments != record.assignments else None)
    tab_all, tab_person = st.tabs(("전체 비교", "직원 상세분석"))
    with tab_all:
        summary_table(view, heading=False, baseline=baseline, key=f"{prefix}_summary_cols")
    with tab_person:
        summary_detail(view, f"{prefix}_summary_person", heading=False)


def load_saved(selected: date) -> dict | None:
    """저장된 야간 근무표를 화면 없이 읽는다 (폰 보기용). render_history_editor와 같은 값 + 원본 data.

    수정 내역을 적용할 수 없으면 ValueError."""
    if not history_store.exists(store_dir(), selected):
        return None
    data = history_store.load(store_dir(), selected)
    from image_import_ui import render_saved_image
    render_saved_image(data)
    plan = data["plan_record"]
    return {"plan": plan, "actual": apply_edits(plan, data["edits"]), "notes": cell_notes(data["edits"]),
            "rebalance": data.get("rebalance"), "lock": history_store.locked_through(data),
            "note": data.get("note", ""), "source": data.get("source"), "data": data,
            "snapshot": data.get("notes_snapshot")}


def render_history_editor(prefix: str, drag_grid, selected: date,
                          summary_table=None, summary_detail=None, mobile: bool = False, leave=None) -> None:
    """Stored schedule of one date: first save, latest revision, corrections.

    mobile: 폰(터치) — 끌기 대신 '눌러서 교환'. 표를 누를 때 교환할지 피로도·사유를 기록할지 고른다.
    기능·저장 방식은 PC와 같다.
    leave: 긴급 반차·이탈 (생성표와 같은 방식 — 시간 칸 누르기 → 그 시간까지 LOCK 빗금, 이름 누르기 → 반차·이탈).
           {"eligible": f(actual, start) -> set[id], "run": f(plan, actual, start, id, half)}"""
    if not history_store.exists(store_dir(), selected):
        return
    data = history_store.load(store_dir(), selected)
    plan = data["plan_record"]
    names = {e.employee_id: e.name for e in plan.context.employees}
    edit_key = f"{prefix}_edits_{selected}_{data['confirmed_at']}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = list(data["edits"])
    edits = st.session_state[edit_key]
    try:
        actual = apply_edits(plan, edits)
    except ValueError as exc:
        st.error(f"수정 내역을 적용할 수 없습니다: {exc}")
        return

    # 2026-10-13 사용자 요청: 날짜를 누르면 근무표가 맨 먼저 — 표 자리를 먼저 잡고 나머지 메뉴는 그 아래
    grid_slot = st.container()
    from night_shift.presentation import barrier_role_summary
    st.caption(barrier_role_summary(actual))
    from night_shift.models import barrier_v2
    if barrier_v2(actual.context) and any(
            r.employee_id == "A" and r.barrier_remove_flag for r in actual.assignments):
        st.warning("저장표의 04시 I1이 통제A입니다. 철수자는 I1로 표시했지만 통제A 차단봉 불참 규칙과 충돌하므로 근무 배정 재편성이 필요합니다.")

    lock = history_store.locked_through(data)
    if lock >= 0:
        info = data.get("rebalance") or {}
        who = names.get(info.get("employee"), info.get("employee"))
        detail = f" · {who} {HOURS[info['from']]}부터 근무불가 ({info.get('reason', '')})" if info.get("from") is not None else ""
        st.info(_md(f"🔒 긴급 재편성 근무표입니다. 18시~{HOURS[lock]}은 재편성 당시 이미 진행된 시간이라 "
                    f"LOCK(빗금)으로 표시하고 드래그로 바꿀 수 없습니다{detail}."))
    views = ("최종 수정본", "최초 저장본") if data["edits"] else ("최초 저장본",)
    if st.session_state.pop(f"{prefix}_return_final_{selected}", False):
        st.session_state[f"{prefix}_view_{selected}"] = views[0]
    view = st.radio("보기", views, horizontal=True, key=f"{prefix}_view_{selected}")
    confirmed = data["confirmed_at"].replace("T", " ")
    edited = data.get("edited_at", "").replace("T", " ")
    st.caption(f"최초 저장 {confirmed}" + (f" · 최종 수정 {edited}" if data["edits"] else " · 수정 없음"))

    delete_key = f"{prefix}_ask_delete_{selected}"
    if st.session_state.get(delete_key):
        st.warning(f"{selected} 근무표를 삭제할까요? 휴지통으로 옮겨지며 언제든 복구할 수 있습니다.")
        d1, d2, _ = st.columns([1, 1, 4])
        if d1.button("삭제", key=f"{prefix}_delete_yes_{selected}"):
            history_store.delete_to_trash(store_dir(), selected)
            st.session_state[delete_key] = False
            st.session_state.pop(edit_key, None)
            st.rerun()
        if d2.button("취소", key=f"{prefix}_delete_no_{selected}"):
            st.session_state[delete_key] = False
            st.rerun()
    elif st.button("🗑 이 날짜 근무표 삭제", key=f"{prefix}_delete_{selected}"):
        st.session_state[delete_key] = True
        st.rerun()

    if view == "최초 저장본" and data["edits"]:
        grid_slot.markdown(f"#### {selected} 최초 저장본")
        st.caption("✋ 꾹 누르고 끌어 교환하면 최초 저장본을 바탕으로 새 최종 수정본을 만듭니다. 최초 저장 기록은 유지됩니다.")
        plan_payload = {**record_grid_payload(plan, editable=True, locked_through=lock), "compact": mobile}
        view_toggle(plan_payload, plan, f"{prefix}_fmview_{selected}")        # FM·유도리 보기 (2026-10-13)
        with grid_slot:
            event = drag_grid(data=plan_payload, key=f"{prefix}_plan_grid_{selected}", default=None)
        if handle_view_event(event, f"{prefix}_fmview_{selected}"):
            event = None
        if isinstance(event, dict) and event.get('kind') == 'cell' and event.get('nonce') != st.session_state.get(f'{prefix}_plan_nonce'):
            st.session_state[f'{prefix}_plan_nonce'] = event.get('nonce')
            edit = {'type':'swap','a':event['source'],'b':event['target']}
            try:
                apply_edits(plan,[edit])
            except ValueError as exc:st.error(str(exc))
            else:
                edits[:] = [edit]
                st.session_state[f"{prefix}_return_final_{selected}"] = True
                st.rerun()
        p1, p2 = st.columns(2)
        from night_shift.source_attachment import render_button
        render_button(data, f"night-{prefix}-plan-{selected}", p2)
        from night_shift.upload_review import revert_button      # 덮어쓰기 전 버전으로 (2026-10-11)
        revert_button(store_dir(), selected, "night", f"night-{prefix}-plan-{selected}", p2)
        if p1.button('💾 실제 근무 저장',key=f'{prefix}_plan_save_{selected}',type='primary'):
            history_store.save_edits(store_dir(), selected, edits)
            st.session_state[f"{prefix}_return_final_{selected}"] = True
            st.rerun()
        _summary_tabs(f"{prefix}_plan", plan, summary_table, summary_detail, view_key=f"{prefix}_fmview_{selected}")
        return {"plan": plan, "actual": actual, "notes": cell_notes(edits), "rebalance": data.get("rebalance"), "lock": lock, "note": data.get("note", ""), "source": data.get("source"), "snapshot": data.get("notes_snapshot")}

    notes = cell_notes(edits)
    cell_key = f"{prefix}_cell_{selected}"
    picked = st.session_state.get(cell_key)

    grid_slot.markdown(f"#### {selected} 저장본 · 실제 근무 수정")   # 표와 함께 맨 위
    tap_swap = mobile and st.radio("표를 누르면", ("피로도·사유 기록", "실제 근무 교환"), horizontal=True,
                                   key=f"{prefix}_tap_mode_{selected}") == "실제 근무 교환"
    if mobile:
        _hints(("✋ 꾹 눌러 끌기 = 교환", "📝 = 주석", "빨간 테두리 = 변경", "빗금 = LOCK"), small=True)
    else:
        _hints(("✋ 칸 끌기 → 실제 근무 교환", "👆 칸 누르기 → 피로도·사유 기록", "📝 누르기 → 주석 보기",
                "빨간 테두리 = 계획과 달라진 칸", "빗금 = LOCK"))
    payload = record_grid_payload(actual, changed_cells(plan, actual), notes=notes,
                                  cell_click=not tap_swap, selected_cell=picked, locked_through=lock)
    payload["tap_swap"] = tap_swap
    payload["compact"] = mobile                          # 폰: 시간 = 줄, 사람 = 열 한 화면 표 (2026-10-05)
    movable_people = {a.employee_id for a in actual.context.attendance
                      if a.present and not a.acts_as_manager and a.display_number is not None}
    for row in payload["rows"]:                          # 번호·자리 교환: 이름(번호) 끌기·누르기 (2026-10-05)
        row["movable"] = row["id"] in movable_people
    lock_key = f"{prefix}_leave_lock_{selected}"
    pending, menus = st.session_state.get(lock_key), {}
    opened = leave is not None and emergency_toggle(      # 눌러야 켜지는 긴급 반차·이탈 (2026-10-05)
        f"{prefix}_emergency_{selected}",
        force=pending is not None or f"{prefix}_leave_request_{selected}" in st.session_state, lock_key=lock_key)
    if opened:
        lock_hours = list(range(lock + 1, 13))            # 07시는 LOCK 뒤에 남는 시간이 없어 제외
        if pending not in lock_hours:
            pending = st.session_state[lock_key] = None
        if pending is not None:
            start = pending + 1
            for pid in leave["eligible"](actual, start):
                menus[pid] = ([{"label": "후반부 반차 (01시 퇴근)", "value": "half"}] if start <= 7 else [])
                menus[pid].append({"label": f"긴급 이탈 ({HOURS[start]}부터)", "value": "leave"})
            for row in payload["rows"]:                  # 이름 고르는 동안 교환·칸 누르기 끔
                row["pick"] = row["id"] in menus
                row["off"] = not row["pick"]
            payload["cell_click"] = False
            payload["tap_swap"] = False
            steps = ([("done", f"① {HOURS[pending]}까지 LOCK ✓"), ("now", "② 빠질 사람 이름 누르기")] if mobile else
                     [("done", f"① {HOURS[pending]}까지 LOCK ✓ (같은 시간을 다시 누르면 취소)"),
                      ("now", "② 빠지는 사람의 이름(노란 칸)을 누르세요"), ("", "③ 재편성표가 아래에 생김")])
        else:
            steps = ([("now", "🚨 긴급: ① 지난 시간 칸 누르기"), ("", "② 이름"), ("", "③ 재편성")] if mobile else
                     [("now", "🚨 긴급 반차·이탈: ① 파란 시간 칸에서 이미 지나간(진행 중) 마지막 시간을 누르세요"),
                      ("", "② 빠지는 사람 이름 누르기"), ("", "③ 재편성표가 아래에 생김")])
        payload.update(lock_hours=lock_hours, pending_lock=pending, menus=menus,
                       steps_html="<div class='steps'>" + "".join(f"<span class='{c}'>{escape(s)}</span>" for c, s in steps)
                                  + "</div>")
    view_toggle(payload, actual, f"{prefix}_fmview_{selected}")            # FM·유도리 보기 (2026-10-13)
    with grid_slot:                                                      # 표는 맨 위 자리에 (2026-10-13)
        event = drag_grid(data=payload, key=f"{prefix}_grid_{selected}", default=None)
    if handle_view_event(event, f"{prefix}_fmview_{selected}"):
        event = None
    queued = st.session_state.pop(f"{prefix}_leave_request_{selected}", None)   # 화면 테스트용 같은 요청 길
    if queued:
        event = {**queued, "nonce": f"queued-{selected}-{len(edits)}-{queued}"}
    nonce_key = f"{prefix}_nonce"
    if isinstance(event, dict) and event.get("nonce") and event["nonce"] != st.session_state.get(nonce_key):
        st.session_state[nonce_key] = event["nonce"]
        if leave is not None and event.get("kind") == "lockhour":
            hour = int(event["t"])
            st.session_state[lock_key] = None if pending == hour else hour
            st.rerun()
        if leave is not None and event.get("kind") == "leave" and pending is not None and event.get("pid") in menus:
            st.session_state[lock_key] = None
            leave["run"](plan, actual, pending + 1, str(event["pid"]), event.get("choice") == "half")
            st.rerun()
        if event.get("kind") == "person":
            edit = {"type": "person", "a": str(event["source"]), "b": str(event["target"])}
            try:
                apply_edits(plan, [*edits, edit])
            except ValueError as exc:
                st.session_state[f"{prefix}_warn"] = str(exc)
            else:
                edits.append(edit)
            st.rerun()
        if event.get("kind") == "cell":
            edit = {"type": "swap", "a": event["source"], "b": event["target"]}
            try:
                apply_edits(plan, [*edits, edit])
            except ValueError as exc:
                st.session_state[f"{prefix}_warn"] = str(exc)
            else:
                edits.append(edit)
            st.rerun()
        elif event.get("kind") == "click":
            cell = [str(event["cell"][0]), int(event["cell"][1])]
            st.session_state[cell_key] = None if picked == cell else cell
            st.rerun()
    if st.session_state.get(f"{prefix}_warn"):
        st.warning(st.session_state.pop(f"{prefix}_warn"))

    if picked:
        p, t = picked
        row = next((r for r in actual.assignments if r.employee_id == p and r.slot.index == t), None)
        if row is not None and row.displayed_assignment.kind.value != "unavailable":
            current = notes.get((p, t))
            with st.container(border=True):
                st.markdown(f"**{names.get(p, p)} · {HOURS[t]} · {row.displayed_assignment.label}** "
                            f"— 기록된 피로도 {row.fatigue_value}")
                c1, c2 = st.columns([1, 3])
                value = c1.radio("실제 피로도", (0, 1, 2), horizontal=True,
                                 index=(current["value"] if current else int(row.fatigue_value)),
                                 key=f"{prefix}_fat_{selected}_{p}_{t}")
                note = c2.text_input("사유 (주석으로 남습니다)", value=current["note"] if current else "",
                                     key=f"{prefix}_note_{selected}_{p}_{t}",
                                     placeholder="예: 01시 I1에서 민원 대응으로 계속 서 있었음")
                b1, b2, b3 = st.columns(3)
                if b1.button("적용", key=f"{prefix}_fat_apply_{selected}_{p}_{t}", type="primary"):
                    edits[:] = [e for e in edits if not (e.get("type") == "fatigue" and
                                                         [str(e["cell"][0]), int(e["cell"][1])] == [p, t])]
                    edits.append({"type": "fatigue", "cell": [p, t], "value": int(value), "note": note.strip()})
                    st.session_state[cell_key] = None
                    st.rerun()
                if current and b2.button("피로도 수정 취소", key=f"{prefix}_fat_del_{selected}_{p}_{t}"):
                    edits[:] = [e for e in edits if not (e.get("type") == "fatigue" and
                                                         [str(e["cell"][0]), int(e["cell"][1])] == [p, t])]
                    st.session_state[cell_key] = None
                    st.rerun()
                if b3.button("닫기", key=f"{prefix}_fat_close_{selected}_{p}_{t}"):
                    st.session_state[cell_key] = None
                    st.rerun()

    ops_key = f"{prefix}_ops_open_{selected}"
    # 야간 FM 저장표 '이날 실제 운영' 한 번에 고르기 (2026-10-20 사용자 확정): 유도리로 근무함 = 이 표의 유도리 운영값
    # (새 생성 I1 22~03시, 옛 저장본 None은 00~03시)을 포스트별 실제 운영 수정으로 넣어 바로 저장한다. 그 칸이 실휴게가
    # 되므로 대폭 휴게·막타임 등 이력 집계에도 그대로 들어간다. 저장된 수정만 바꾸고 아직 저장 안 한 다른 수정은 건드리지 않는다.
    if plan.context.effective_mode.value == "FM" and plan.context.flexible_from_slot is None:
        flex_ops = night_flex_operations(plan)
        is_flex = flex_applied(data["edits"], flex_ops)
        choice = st.radio("이날 실제 운영", ("FM 그대로", "유도리로 근무함"), index=int(is_flex), horizontal=True,
                          key=f"{prefix}_actual_mode_{selected}_{int(is_flex)}",
                          help="유도리로 근무함: " + ", ".join(f"{p} {HOURS[lo]}~{HOURS[hi]} {'휴게성' if s == 'rest' else '좌식'}"
                                                         for p, lo, hi, s in flex_ops) + " — 고르면 바로 저장됩니다.")
        if (choice == "유도리로 근무함") != is_flex:
            history_store.save_edits(store_dir(), selected, toggle_flex(data["edits"], flex_ops, not is_flex))
            edits[:] = toggle_flex(edits, flex_ops, not is_flex)
            st.session_state[f"{prefix}_return_final_{selected}"] = True     # 저장한 최종 수정본 화면으로 (선택칸이 거기 있음)
            st.toast("이날 실제 운영을 유도리로 저장했습니다." if not is_flex else "이날 실제 운영을 FM 그대로로 저장했습니다.")
            st.rerun()
    if st.button("✏️ 포스트별 실제 운영 수정" if not st.session_state.get(ops_key) else "포스트별 수정 닫기",
                 key=f"{prefix}_ops_toggle_{selected}"):
        st.session_state[ops_key] = not st.session_state.get(ops_key)
        st.rerun()
    if st.session_state.get(ops_key):
        st.caption(_md("바뀐 포스트만 운영 방식을 고르세요. '변경 없음'인 포스트는 그대로 둡니다. "
                       "'끝'은 그렇게 운영한 마지막 근무투입시간입니다 (예: 00시~03시 = 00·01·02·03시 네 칸). "
                       "같은 포스트에 겹치게 다시 적용하면 앞의 범위는 지워지고 마지막에 적용한 범위로 바뀝니다 "
                       "(겹치지 않는 별도 범위는 그대로 남음)."))
        posts = sorted({r.displayed_assignment.label for r in actual.assignments
                        if r.displayed_assignment.kind.value == "post"})
        chosen = {}
        for post in posts:
            c = st.columns([1, 1.4, 1.4, 2.4])
            c[0].markdown(f"<div style='padding-top:1.9rem;font-weight:600'>{post}</div>", unsafe_allow_html=True)
            start = c[1].selectbox("시작", range(14), format_func=lambda t: HOURS[t],
                                   key=f"{prefix}_ops_from_{selected}_{post}")
            end = c[2].selectbox("끝 (근무투입시간)", range(14), index=13, format_func=lambda t: HOURS[t],
                                 key=f"{prefix}_ops_to_{selected}_{post}")
            state = c[3].radio("실제 운영", ("변경 없음", "좌식", "휴게성"), horizontal=True,
                               key=f"{prefix}_ops_state_{selected}_{post}")
            if state != "변경 없음":
                chosen[post] = (int(start), int(end), "seated" if state == "좌식" else "rest")
        if st.button("선택한 포스트 적용", key=f"{prefix}_ops_apply_{selected}", type="primary",
                     disabled=not chosen):
            bad = [post for post, (lo, hi, _) in chosen.items() if lo > hi]
            if bad:
                st.session_state[f"{prefix}_warn"] = f"{', '.join(bad)}: 시작 시간이 끝 시간보다 늦습니다."
            else:
                for post, (lo, hi, state) in chosen.items():   # 겹치는 시간은 마지막 적용이 덮어씀
                    edits[:] = add_state_edit(edits, post, lo, hi, state)
                for post in chosen:  # reset the pickers to '변경 없음'
                    st.session_state.pop(f"{prefix}_ops_state_{selected}_{post}", None)
            st.rerun()

    if edits:
        st.markdown("**수정 내역**")
        for index, edit in enumerate(list(edits)):
            c1, c2 = st.columns([6, 1])
            c1.write(_md(f"{index + 1}. {describe_edit(edit, names)}"))
            if c2.button("삭제", key=f"{prefix}_del_{selected}_{index}"):
                edits.pop(index)
                st.rerun()
    saved = edits == data["edits"]
    c1, c3, c2 = st.columns(3)
    from night_shift.source_attachment import render_button   # 원본 보기 = 실제 근무 저장 바로 옆 (2026-10-07)
    render_button(data, f"night-{prefix}-{selected}", c3)
    from night_shift.upload_review import revert_button          # 덮어쓰기 전 버전으로 (2026-10-11)
    revert_button(store_dir(), selected, "night", f"night-{prefix}-{selected}", c3)
    # 2026-10-04 사용자 요청: 항상 켜 두고, 마지막으로 누른 시점의 화면 근무표를 최종 실제 근무로 덮어쓴다.
    if c1.button("💾 실제 근무 저장", key=f"{prefix}_save_{selected}", type="primary",
                 help="지금 화면의 근무표를 이 날의 최종 실제 근무로 저장합니다 (누를 때마다 덮어씀)."):
        history_store.save_edits(store_dir(), selected, edits)
        st.session_state["flash"] = (f"{selected} 실제 근무를 최종본으로 저장했습니다. "
                                     "이후 근무표 생성에 이 실제 기록이 반영됩니다.")
        st.rerun()
    if c2.button("저장본으로 되돌리기", key=f"{prefix}_revert_{selected}", disabled=saved):
        st.session_state[edit_key] = list(data["edits"])
        st.rerun()
    if not saved:
        st.caption("저장하지 않은 수정이 있습니다. '💾 실제 근무 저장'을 누르면 지금 화면이 최종본이 됩니다.")

    _summary_tabs(prefix, actual, summary_table, summary_detail, baseline_record=plan, view_key=f"{prefix}_fmview_{selected}")
    return {"plan": plan, "actual": actual, "notes": notes, "rebalance": data.get("rebalance"), "lock": lock, "note": data.get("note", ""), "source": data.get("source"), "snapshot": data.get("notes_snapshot")}


# ---------------------------------------------------------------- monthly report
def _leave_label(attendance, handover) -> str | None:
    if not attendance.present:
        return "결근" if attendance.acts_as_manager and attendance.display_number is None else "연차"
    slots = attendance.available_slot_indices
    if slots is None or len(slots) == 14:
        return None
    if tuple(slots) == tuple(range(7, 14)):
        return "전반부 반차"
    if tuple(slots) == tuple(range(0, 7)):
        return "후반부 반차"
    if slots and slots[0] == 0:
        extra = " · 준호 관리자 대행" if handover and attendance.acts_as_manager else ""
        return f"긴급 이탈 {HOURS[len(slots)]}부터{extra}"
    return f"부분 근무 {HOURS[slots[0]]}~"


def field_changes(day: date, plan, actual, edits: list, names: dict) -> list[dict]:
    """그날 현장에서 생긴 변동(근무 교환·피로도/사유 주석·실제 운영 변경)과 사람별 피로도 변화 (2026-10-05).
    반환: [{'날짜','직원','내용','피로도 변화'}] — 피로도가 바뀐 사람마다 그 사람에 관련된 변경을 붙인다."""
    from night_shift.actual_edit import describe_edit
    if not edits:
        return []
    before, after = calculate_all_stats(plan), calculate_all_stats(actual)
    out = []
    for pid, person in after.items():
        delta = person.fatigue_value - (before[pid].fatigue_value if pid in before else 0)
        mine = []
        for edit in edits:
            kind = edit.get("type")
            involved = ({str(edit["a"][0]), str(edit["b"][0])} if kind == "swap" else
                        {str(edit["a"]), str(edit["b"])} if kind == "person" else
                        {str(edit["cell"][0])} if kind == "fatigue" else None)   # state = 그 시간 해당 포스트 전원
            if involved is None and delta or involved and pid in involved:
                mine.append(describe_edit(edit, names))
        if delta or mine:
            out.append({"날짜": day.strftime("%m/%d"), "직원": names.get(pid, pid),
                        "내용": " · ".join(mine) or "현장 기록 변경", "피로도 변화": f"{delta:+g}"})
    return out


def _signed(value: float) -> str:
    """+0.4 / -0.2 / 0.0 (반올림해 0이면 부호 없이)."""
    value = round(value, 1)
    return "0.0" if value == 0 else f"{value:+.1f}"


def render_monthly(shift_date: date) -> list[dict]:
    """Monthly average fatigue per worker and leave records, from saved actual nights."""
    dates = history_store.list_dates(store_dir())
    if not dates:
        st.info("저장된 근무표가 없습니다. 근무표를 확정 저장하면 월간 피로도와 연차 기록이 여기에 쌓입니다.")
        return []
    months = sorted({(d.year, d.month) for d in dates} | {(shift_date.year, shift_date.month)}, reverse=True)
    year, month = st.selectbox("월 선택", months, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월",
                               key="monthly_month")
    days = [d for d in dates if (d.year, d.month) == (year, month) and d <= shift_date]
    if not days:
        st.info(f"{shift_date:%Y년 %m월 %d일} 기준으로 이 달에 저장된 근무표가 없습니다.")
        return []
    totals: dict[str, dict] = {}
    leaves = []
    changes = []                                         # 현장 변동 (월간 분석에서만 설명, 2026-10-05)
    from night_shift import leave_schedule
    for day in days:
        record = history_store.actual_record(store_dir(), day)
        names = {e.employee_id: e.name for e in record.context.employees}
        try:
            data = history_store.load(store_dir(), day)
            day_changes = field_changes(day, history_store.record_from_json(data["plan"]), record,
                                        data.get("edits") or [], {**names, "A": "통제"})
        except Exception:
            day_changes = []
        changes.extend(day_changes)
        others = leave_schedule.other_labels(store_dir(), day, "night", list(names.values()))   # 기타(근무 제외)
        stats = calculate_all_stats(record)
        # 같은 날 동료 대비(2026-10-19 사용자 요청): 그날 온전 출근한 다른 일반근무자 평균과의 차이.
        # 온전 출근일 구성이 달라 월 평균만으로는 생기는 착시(가벼운 날 빠짐 등)를 구분한다.
        full_general = {a.employee_id: stats[a.employee_id].fatigue_value for a in record.context.attendance
                        if a.present and a.is_general_worker and not a.acts_as_manager and a.employee_id in stats
                        and _leave_label(a, record.context.manager_handover) is None}
        for a in record.context.attendance:
            label = _leave_label(a, record.context.manager_handover)
            name = "통제" if a.acts_as_manager and a.display_number is None else names[a.employee_id]
            if label in ("연차", "결근") and names.get(a.employee_id) in others:
                note = others[names[a.employee_id]]
                label = "기타" + (f"({note})" if note else "")
            item = totals.setdefault(a.employee_id, {"직원": name, "온전 출근일": 0, "fatigue": 0,
                                                     "work": 0, "연차": 0, "반차": 0, "기타": 0, "peer": 0.0, "peer_n": 0})
            if label:
                leaves.append({"날짜": day.strftime("%m/%d"), "직원": name, "구분": label})
                if label in ("연차", "결근"):
                    item["연차"] += 1
                elif label.startswith("기타"):
                    item["기타"] += 1
                elif "반차" in label:
                    item["반차"] += 1
            person = stats.get(a.employee_id)
            # Averages count only nights worked in full (no 연차·반차·이탈).
            if a.present and label is None and person is not None:
                item["온전 출근일"] += 1
                item["fatigue"] += person.fatigue_value
                item["work"] += person.actual_work_time_value
                others_today = [v for pid, v in full_general.items() if pid != a.employee_id]
                if a.employee_id in full_general and others_today:
                    item["peer"] += person.fatigue_value - sum(others_today) / len(others_today)
                    item["peer_n"] += 1
    rows = []
    for employee_id in sorted(totals, key=lambda p: (p != "A", p)):
        item = totals[employee_id]
        nights = item["온전 출근일"]
        rows.append({**item, "id": employee_id, "is_manager": employee_id == "A", "평균 피로도": round(item["fatigue"] / nights, 2) if nights else None,
                     "평균 실근무": round(item["work"] / nights, 2) if nights else None,
                     "동료 대비(±)": _signed(item["peer"] / item["peer_n"]) if item["peer_n"] else "–",
                     "집계 기준일": shift_date.isoformat(),
                     "현장 변동": [c for c in changes if c["직원"] == item["직원"]]})
    st.markdown(f"##### {year}년 {month}월 근무자별 피로도 · {shift_date:%m/%d}까지 저장된 {len(days)}일, 실제 근무 기준")
    st.dataframe(pd.DataFrame(rows)[["직원", "온전 출근일", "평균 피로도", "동료 대비(±)", "평균 실근무", "연차", "반차", "기타"]],
                 hide_index=True, width="stretch")
    st.caption(f"선택한 {shift_date:%Y-%m-%d} 당일까지의 저장된 실제 근무만 집계합니다. 이후 날짜는 제외하며, 평균은 연차·반차·긴급 이탈 없이 온전히 출근한 날만 계산합니다. "
               "'동료 대비(±)'는 같은 날 온전 출근한 다른 일반근무자 평균과의 차이를 밤당 평균한 값입니다(+면 같은 날 동료보다 많이 맡음). "
               "평균 피로도는 출근한 날 구성(인원이 적어 모두 높은 날 등)에 따라 달라지므로, 공평한지는 이 값으로 봅니다.")
    chart = monthly_dot_chart(rows)
    if chart is not None:
        st.markdown("##### 월간 평균 피로도 (점이 팀 평균선보다 오른쪽이면 부담이 큰 사람)")
        try:
            st.altair_chart(chart, width="stretch")
        except TypeError:  # older Streamlit
            st.altair_chart(chart, use_container_width=True)
    st.markdown("##### 현장 변동 (근무표 생성 후 실제로 바뀐 것, 주석 참조)")
    if changes:
        st.dataframe(pd.DataFrame(changes), hide_index=True, width="stretch")
        st.caption("근무표 특이사항은 생성 당시 기준이라 이 변동을 넣지 않습니다. 월간 평균 피로도에는 이 변동이 포함됩니다.")
    else:
        st.caption("이 달에 현장에서 바뀐 기록이 없습니다.")
    st.markdown("##### 연차·반차·이탈 기록")
    if leaves:
        st.dataframe(pd.DataFrame(leaves), hide_index=True, width="stretch")
    else:
        st.caption("이 달에 기록된 연차·반차가 없습니다.")
    return rows


# ---------------------------------------------------------------- recent duties (특이사항 표)
ZONE = {"upper": "상층", "middle": "중층", "lower": "하층"}


def _duty_tokens(record) -> dict:
    out = {}
    for r in sorted(record.assignments, key=lambda r: r.slot.index):
        hour = f"{(18 + r.slot.index) % 24:02d}"
        tokens = out.setdefault(r.employee_id, [])
        if barrier_history_counts(record.context) and r.barrier_install_flag:
            tokens.append("설치")
        if barrier_history_counts(record.context) and r.barrier_remove_flag:
            tokens.append("철수")
        if r.actual_post_or_work_type.kind.value == "patrol":
            tokens.append(ZONE.get(r.actual_post_or_work_type.label, r.actual_post_or_work_type.label) + hour)
    return out


def duty_frame(shift_date: date, current=None) -> pd.DataFrame | None:
    """근무자별 최근 3싸이클(6근무) + 이번 근무의 차단봉 설치·철수와 순찰 구역."""
    nights = sorted(history_store.recent_actuals(store_dir(), shift_date, limit=6),
                    key=lambda r: r.context.shift_start_date)
    records = [(r.context.shift_start_date.strftime("%m/%d"), r) for r in nights]
    if current is not None:
        records.append((f"이번 {shift_date:%m/%d}", current))
    if not records:
        return None
    names = {}
    for _, record in records:
        for e in record.context.employees:
            names[e.employee_id] = "통제" if e.employee_id == "A" else e.name
    rows = []
    for pid in sorted(names, key=lambda p: (p != "A", p)):
        row = {"직원": names[pid]}
        install = remove = 0
        zones = {"상층": 0, "중층": 0, "하층": 0}
        for label, record in records:
            present = any(a.employee_id == pid and a.present for a in record.context.attendance)
            tokens = _duty_tokens(record).get(pid, [])
            row[label] = "·".join(tokens) if tokens else ("-" if present else "결근")
            if not label.startswith("이번"):
                install += tokens.count("설치")
                remove += tokens.count("철수")
                for t in tokens:
                    if t[:2] in zones:
                        zones[t[:2]] += 1
        row.update({"설치(6근무)": install, "철수(6근무)": remove,
                    "상층": zones["상층"], "중층": zones["중층"], "하층": zones["하층"]})
        rows.append(row)
    return pd.DataFrame(rows)


ZONE_COLORS = {"상층": "#2a78d6", "중층": "#eb6834", "하층": "#1baf7a"}   # 검증된 범주색 1~3


def duty_grid_html(frame: pd.DataFrame) -> str:
    """duty_frame을 사람 × 날짜 격자로: ▲설치 ▼철수, 순찰은 구역 색 점 + '상21' 글자."""
    total_cols = ["설치(6근무)", "철수(6근무)", "상층", "중층", "하층"]
    date_cols = [c for c in frame.columns if c not in ("직원", *total_cols)]
    css = ("<style>.duty{border-collapse:separate;border-spacing:0;width:100%;font-size:.82rem}"
           ".duty th{font-weight:600;color:#475569;padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:center;white-space:nowrap}"
           ".duty td{padding:5px 6px;border-bottom:1px solid #f1f5f9;text-align:center;vertical-align:middle}"
           ".duty td.name{text-align:left;font-weight:600;color:#0f172a;white-space:nowrap}"
           ".duty td.now{background:#f8fafc}.duty .chip{display:inline-flex;align-items:center;gap:3px;"
           "margin:1px 3px;white-space:nowrap;color:#1e293b}.duty .dot{width:9px;height:9px;border-radius:50%;"
           "display:inline-block}.duty .bar{font-weight:700;color:#334155}.duty .muted{color:#cbd5e1}"
           ".duty .off{color:#94a3b8;font-size:.75rem}.duty td.num{font-variant-numeric:tabular-nums;color:#334155}"
           ".duty td.hot{font-weight:800;color:#0f172a;background:#fef3c7}</style>")
    maxima = {c: frame[c].max() for c in total_cols}
    head = "".join(f"<th>{escape(c)}</th>" for c in ["직원", *date_cols])
    head += "".join(f"<th>{escape(c.replace('(6근무)', ''))}</th>" for c in total_cols)
    rows = []
    for _, r in frame.iterrows():
        cells = [f"<td class='name'>{escape(str(r['직원']))}</td>"]
        for c in date_cols:
            value = str(r[c])
            now = " now" if c.startswith("이번") else ""
            if value == "-":
                cells.append(f"<td class='muted{now}'>·</td>")
                continue
            if value == "결근":
                cells.append(f"<td class='off{now}'>결근</td>")
                continue
            chips = []
            for token in value.split("·"):
                if token == "설치":
                    chips.append("<span class='chip bar' title='차단봉 설치'>▲설치</span>")
                elif token == "철수":
                    chips.append("<span class='chip bar' title='차단봉 철수'>▼철수</span>")
                else:
                    zone, hour = token[:2], token[2:]
                    chips.append(f"<span class='chip' title='{zone} 순찰'><span class='dot' "
                                 f"style='background:{ZONE_COLORS.get(zone, '#94a3b8')}'></span>{zone}</span>")
            cells.append(f"<td class='{now.strip()}'>{''.join(chips)}</td>")
        for c in total_cols:
            hot = " hot" if maxima[c] and r[c] == maxima[c] and r[c] >= 2 else ""
            cells.append(f"<td class='num{hot}'>{int(r[c])}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    legend = ("<div style='font-size:.75rem;color:#475569;margin-top:6px'>"
              + " · ".join(f"<span class='chip'><span class='dot' style='background:{v}'></span>{k}</span>"
                           for k, v in ZONE_COLORS.items())
              + " · ▲설치 · ▼철수 · 노란 칸 = 최근 6근무 중 가장 많이 맡은 사람(2회 이상)</div>")
    # 흰 바탕 패널: 다크모드에서도 글자가 묻히지 않게 (근무표와 같은 '종이' 모양)
    return (css + f"<div style='{PAPER}'><div style='overflow-x:auto'><table class='duty'><thead><tr>" + head
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            + legend.replace("class='chip'", "style='display:inline-flex;align-items:center;gap:3px'")
            .replace("class='dot' style='", "style='width:9px;height:9px;border-radius:50%;display:inline-block;")
            + "</div><div style='height:16px'></div>")   # 아래 안내 글과 겹침 방지 (Streamlit 마지막 요소 음수 여백, 2026-10-13)


# 직접 그린 HTML 표·격자의 공통 바탕: 테마와 관계없이 흰 바탕·검은 글자 (다크모드 가시성)
PAPER = "background:#fff;color:#111827;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px"


def is_dark() -> bool:
    """지금 화면이 다크모드인지 (Streamlit이 배경색으로 판단)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:          # 테스트 등 화면이 없는 실행
        return False


def monthly_dot_chart(rows: list[dict]):
    """월간 평균 피로도 점 그래프 (일반근무자, 팀 평균 세로선)."""
    import altair as alt
    data = pd.DataFrame([r for r in rows if not r.get("is_manager") and r.get("평균 피로도") is not None])
    if len(data) < 2:
        return None
    mean = float(data["평균 피로도"].mean())
    lo, hi = float(data["평균 피로도"].min()), float(data["평균 피로도"].max())
    pad = max(0.5, (hi - lo) * 0.25)
    dark = is_dark()                                   # 다크모드면 글자·격자선을 밝게
    ink, faint, grid = ("#e5e7eb", "#9ca3af", "#334155") if dark else ("#334155", "#64748b", "#f1f5f9")
    x = alt.X("평균 피로도:Q", scale=alt.Scale(domain=[round(lo - pad, 1), round(hi + pad, 1)]),
              axis=alt.Axis(grid=True, gridColor=grid, title="밤당 평균 피로도 (온전 출근일)"))
    y = alt.Y("직원:N", sort="-x", axis=alt.Axis(title=None, labelFontSize=12))
    dots = alt.Chart(data).mark_circle(size=140, color="#60a5fa" if dark else "#2a78d6", opacity=1).encode(
        x=x, y=y, tooltip=["직원", alt.Tooltip("평균 피로도:Q", format=".2f"), "온전 출근일"])
    labels = alt.Chart(data).mark_text(dx=12, align="left", fontSize=11, color=ink).encode(
        x=x, y=y, text=alt.Text("평균 피로도:Q", format=".1f"))
    rule = alt.Chart(pd.DataFrame({"m": [mean]})).mark_rule(strokeDash=[4, 4], color=faint, size=2).encode(x="m:Q")
    rule_label = alt.Chart(pd.DataFrame({"m": [mean], "t": [f"팀 평균 {mean:.1f}"]})).mark_text(
        dy=-8, align="left", dx=4, fontSize=11, color=faint).encode(x="m:Q", y=alt.value(0), text="t:N")
    return (rule + rule_label + dots + labels).properties(height=34 * len(data) + 30)


def recent_fatigue_html(shift_date: date, view: str | None = None) -> str:
    """선택일 이전 최근 실제 6근무. 날짜 링크로 저장된 근무표 이동. 맨 아래 평균 줄(가장 높음 주황·낮음 파랑)."""
    from urllib.parse import urlencode
    records = sorted(history_store.recent_actuals(store_dir(), shift_date, limit=6),
                     key=lambda r: r.context.shift_start_date)
    if not records:
        return ""
    names = {}
    for record in records:
        names.update({e.employee_id: "통제A" if e.employee_id == "A" else e.name
                      for e in record.context.employees})
    people = sorted(names, key=lambda p: (p != "A", p))
    header = "<th>날짜</th>" + "".join(f"<th>{escape(names[p])}</th>" for p in people)
    rows = []
    totals = {pid: [] for pid in people}
    for record in records:
        day = record.context.shift_start_date
        params = {"night_date": day.isoformat()}
        if view in ("pc", "mobile"):
            params["view"] = view
        href = escape("?" + urlencode(params), quote=True)
        stats = calculate_all_stats(record)
        full = [person.fatigue_value for person in stats.values()
                if not person.is_manager and person.available_time == 14]
        day_average = sum(full) / len(full) if full else None
        cells = []
        for pid in people:
            person = stats.get(pid)
            if person is None:
                cells.append('<td class="off">—</td>')
            else:
                partial = person.available_time < 14
                value = day_average if partial else person.fatigue_value
                if value is not None:
                    totals[pid].append(value)
                suffix = f'<sup title="반차·이탈: 실제 {person.fatigue_value:g}점, 당일 온전 일반근무자 평균 대입">반</sup>' if partial else ""
                number = f"{value:.1f}".rstrip("0").rstrip(".") if value is not None else "—"
                cells.append(f"<td>{number}{suffix}</td>")
        rows.append(f'<tr><td><a target="_self" href="{href}" aria-label="{day.isoformat()} 야간 근무표">{day:%m/%d}</a></td>' + "".join(cells) + "</tr>")
    # 평균 줄: 일반근무자(통제A 제외) 중 가장 높은 사람 주황·가장 낮은 사람 파랑 (2026-10-14 사용자 요청, 동점은 모두)
    averages = {pid: round(sum(totals[pid]) / len(totals[pid]), 2) for pid in people if totals[pid]}
    general = {p: v for p, v in averages.items() if p != "A"}
    top = max(general.values()) if len(general) >= 2 else None
    bottom = min(general.values()) if len(general) >= 2 else None
    average_cells = ""
    for pid in people:
        if pid not in averages:
            average_cells += '<td class="off">—</td>'
            continue
        tag = ("" if pid == "A" or top == bottom else
               ' class="more" title="최근 6근무 평균 가장 높음"' if averages[pid] == top else
               ' class="less" title="최근 6근무 평균 가장 낮음"' if averages[pid] == bottom else "")
        average_cells += f"<td{tag}>{averages[pid]:.2f}</td>"
    footer = '<tfoot><tr><th>평균</th>' + average_cells + '</tr></tfoot>'
    css = '<style>.recent-fatigue tfoot td.less{color:#3B82F6}.recent-fatigue tfoot td.more{color:#F97316}.recent-fatigue{width:100%;max-width:760px;table-layout:fixed;border-collapse:collapse;font-size:clamp(11px,2.9vw,13px);font-variant-numeric:tabular-nums}.recent-fatigue th,.recent-fatigue td{text-align:center;padding:7px 1px;border-bottom:1px solid #94a3b833;overflow-wrap:anywhere}.recent-fatigue th:first-child{width:52px}.recent-fatigue a{display:block;padding:3px 0;color:#3182f6;font-weight:600;text-decoration:underline}.recent-fatigue sup{font-size:9px;margin-left:1px}.recent-fatigue .off{opacity:.45} .recent-fatigue tfoot{font-weight:700;background:#3182f610}.recent-fatigue tfoot td{border-top:1px solid #94a3b855}</style>'
    return css + '<table class="recent-fatigue"><thead><tr>' + header + '</tr></thead><tbody>' + "".join(rows) + '</tbody>' + footer + '</table>'


def _last_rest_people(record) -> tuple[dict, list[str]]:
    """그 밤 07시(막타임) 실휴게를 받은 일반근무자와 그 밤 일반근무자 이름표. 관리자(통제A·대행) 제외."""
    stats = calculate_all_stats(record)
    names = {p: s.name for p, s in stats.items() if not s.is_manager}
    rest = [r.employee_id for r in record.assignments
            if r.slot.index == 13 and r.employee_id in names and r.actual_rest_time_value == 1]
    return names, rest


def last_rest_table_html(shift_date: date, current=None) -> str:
    """막타임(07시) 휴게 표 (2026-10-13 사용자 요청: 비고 문장 대신 순찰표처럼). 사람 × 최근 6근무(+이번 근무),
    받은 칸에만 🛌. 위 한 줄 판정(최근 6근무 고르기·직전에 이어 또 받음). 저장된 실제 근무 기준, 관리자 제외."""
    store = store_dir()
    recent = sorted(history_store.recent_actuals(store, shift_date, limit=6), key=lambda r: r.context.shift_start_date)
    if not recent:
        return ""
    nights = [(f"{r.context.shift_start_date:%m/%d}", *_last_rest_people(r)) for r in recent]
    if current is not None:
        nights.append(("이번", *_last_rest_people(current)))
    names = {}
    for _, day_names, _ in nights:
        names.update(day_names)
    people = sorted(names, key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))
    recent6 = {p: sum(p in rest for _, _, rest in nights) for p in people}
    repeats, prev = [], set()
    for label, day_names, rest in nights:
        repeats += [f"{label} {day_names[p]}" for p in rest if p in prev]
        prev = (prev - set(day_names)) | set(rest)
    # 2026-10-13 사용자 요청: 날짜별로 누가 07시 휴게했는지만 — 점·실선·횟수 열·주석 없음, 폰 한 화면(고정 폭)
    css = ("<style>.lastrest{border-collapse:collapse;width:100%;table-layout:fixed;font-size:.82rem}"
           ".lastrest th{font-weight:600;color:#475569;padding:6px 2px;border-bottom:1px solid #e2e8f066;text-align:center;"
           "white-space:nowrap;font-size:.78rem}.lastrest th:first-child{width:3.6em}"
           ".lastrest td{padding:6px 2px;border-bottom:1px solid #e2e8f033;text-align:center;height:1.6em}"
           ".lastrest td.name{text-align:left;font-weight:600;white-space:nowrap}</style>")
    gap = max(recent6.values()) - min(recent6.values()) if recent6 else 0
    head = "<th>직원</th>" + "".join(f"<th>{escape(label)}</th>" for label, _, _ in nights)
    rows = []
    for p in people:
        cells = [f"<td class='name'>{escape(names[p])}</td>"]
        cells += [f"<td>{'🛌' if p in rest else ''}</td>" for _, _, rest in nights]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    verdict = ("배정 기준: 직전 출근 수혜자 제외 · 한 번도 안 받은 사람 먼저, 그다음 마지막 수혜 뒤 본인 출근이 많은 사람 · "
               "같은 순번은 최근 3싸이클 평균 피로도 높은 사람 우선 · "
               + f"표에 표시된 수혜 횟수 차이 {gap}회 · "
               + ("연속 수혜 없음" if not repeats else "연속 수혜: " + ", ".join(repeats)))
    return (css + f"<div style='font-size:.85rem;margin:2px 0 4px'>{escape(verdict)}</div>"
            + "<table class='lastrest'><tr>" + head + "</tr>" + "".join(rows) + "</table>"
            + "<div style='height:12px'></div>")

def night_flex_operations(plan) -> tuple:
    """이 야간 표를 유도리로 운영했을 때의 포스트별 운영값 — models.post_operation과 같은 기준
    (새 생성 표는 저장된 값 I1 22~03시, 옛 저장본 None은 종전 00~03시)."""
    from night_shift.models import DEFAULT_POST_OPERATIONS
    ops = plan.context.post_operations
    return tuple(tuple(op) for op in (DEFAULT_POST_OPERATIONS if ops is None else ops))


def flex_applied(edits: list[dict], flex_ops) -> bool:
    """저장된 수정에 유도리 운영값이 전부 그대로 들어 있나 (이날 실제 운영 = 유도리)."""
    return bool(flex_ops) and all(any(
        e.get("type") == "state" and int(e["from"]) == lo and int(e["to"]) == hi and e.get("posts", {}).get(post) == state
        for e in edits) for post, lo, hi, state in flex_ops)


def toggle_flex(edits: list[dict], flex_ops, on: bool) -> list[dict]:
    """유도리 운영값을 포스트별 실제 운영 수정으로 넣거나(on) 그 수정만 뺀다(off). 다른 수정은 그대로."""
    out = list(edits)
    for post, lo, hi, state in flex_ops:
        if on:
            out = add_state_edit(out, post, lo, hi, state)
        else:
            out = [e for e in out if not (e.get("type") == "state" and int(e["from"]) == lo and int(e["to"]) == hi
                                          and e.get("posts") == {post: state})]
    return out


def _big_rest_people(record) -> tuple[dict[str, str], list[str]]:
    """그 밤 대폭 휴게(23시~07시 이전, 3시간 이상 연속 실휴게)를 받은 일반근무자. 관리자(통제A·대행) 제외."""
    from night_shift.models import BIG_REST_STARTS
    stats = calculate_all_stats(record)
    names = {p: s.name for p, s in stats.items() if not s.is_manager}
    rest = {(r.employee_id, r.slot.index) for r in record.assignments if r.actual_rest_time_value == 1}
    big = [p for p in names if any(all((p, t) in rest for t in (s, s + 1, s + 2)) for s in BIG_REST_STARTS)]
    return names, big


def big_rest_table_html(shift_date: date, current=None) -> str:
    """대폭 휴게 표 (2026-10-20): 사람 × 최근 6근무(+이번 근무, 10/04 야간부터), 받은 칸에 🛌. 막타임 표와 같은 모양."""
    recent = sorted(history_store.recent_actuals(store_dir(), shift_date, limit=6), key=lambda r: r.context.shift_start_date)
    nights = [(f"{r.context.shift_start_date:%m/%d}", *_big_rest_people(r)) for r in recent
              if r.context.shift_start_date >= date(2026, 10, 4)]
    if current is not None:
        nights.append(("이번", *_big_rest_people(current)))
    if not nights:
        return ""
    names = {}
    for _, day_names, _ in nights:
        names.update(day_names)
    people = sorted(names, key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))
    counts = {p: sum(p in big for _, _, big in nights) for p in people}
    gap = max(counts.values()) - min(counts.values()) if counts else 0
    css = ("<style>.lastrest{border-collapse:collapse;width:100%;table-layout:fixed;font-size:.82rem}"
           ".lastrest th{font-weight:600;color:#475569;padding:6px 2px;border-bottom:1px solid #e2e8f066;text-align:center;"
           "white-space:nowrap;font-size:.78rem}.lastrest th:first-child{width:3.6em}"
           ".lastrest td{padding:6px 2px;border-bottom:1px solid #e2e8f033;text-align:center;height:1.6em}"
           ".lastrest td.name{text-align:left;font-weight:600;white-space:nowrap}</style>")
    head = "<th>직원</th>" + "".join(f"<th>{escape(label)}</th>" for label, _, _ in nights)
    rows = ["<tr>" + f"<td class='name'>{escape(names[p])}</td>"
            + "".join(f"<td>{'🛌' if p in big else ''}</td>" for _, _, big in nights) + "</tr>" for p in people]
    verdict = ("배정 기준: 가능한 많은 사람에게 → 한 번도 안 받은 사람 먼저, 그다음 마지막 수혜 뒤 본인 출근이 많은 사람 · "
               "같은 순번은 최근 3싸이클 평균 피로도 높은 사람 우선 · "
               f"막타임(07시)과는 따로 순번 · 표에 표시된 수혜 횟수 차이 {gap}회")
    return (css + f"<div style='font-size:.85rem;margin:2px 0 4px'>{escape(verdict)}</div>"
            + "<table class='lastrest'><tr>" + head + "</tr>" + "".join(rows) + "</table>"
            + "<div style='height:12px'></div>")


def link_night_dates(text: str, year: int) -> str:
    """문장 속 'MM/DD'가 저장된 야간 근무표 날짜면 그 근무표로 가는 링크로 (2026-10-13 사용자 요청: 현장 변동 날짜 클릭).
    결과는 HTML(같은 창 이동, PC·폰 view 유지). 나머지 글자는 그대로 이스케이프."""
    from urllib.parse import urlencode
    saved = set(history_store.list_dates(store_dir()))
    view = st.query_params.get("view")
    out, last = [], 0
    for m in re.finditer(r"(?<!\d)(\d{2})/(\d{2})(?!\d)", text):
        try:
            day = date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if day not in saved:
            continue
        params = {"night_date": day.isoformat(), **({"view": view} if view in ("pc", "mobile") else {})}
        out.append(escape(text[last:m.start()]))
        out.append(f'<a target="_self" href="{escape("?" + urlencode(params), quote=True)}" '
                   f'style="color:#3182f6;font-weight:600;text-decoration:underline" '
                   f'aria-label="{day.isoformat()} 야간 근무표">{m.group(0)}</a>')
        last = m.end()
    out.append(escape(text[last:]))
    return "".join(out)


def apply_fatigue_navigation() -> None:
    raw = st.query_params.get("night_date")
    if not raw:
        return
    try:
        day = date.fromisoformat(raw)
        if history_store.exists(store_dir(), day):
            st.session_state["shift_date"] = day
            st.session_state["app_tab"] = "🗓 근무표"
    except (ValueError, TypeError):
        pass
    del st.query_params["night_date"]


def render_recent_fatigue(shift_date: date) -> None:
    html = recent_fatigue_html(shift_date, st.query_params.get("view"))
    if html:
        st.markdown("**참조한 최근 3싸이클 · 피로도**")
        st.markdown(html, unsafe_allow_html=True)
        st.caption("평균=최근 6근무 단순평균(미출근 제외) · 주황=가장 높음 · 파랑=가장 낮음 · "
                   "반=당일 온전 일반근무자 평균 대입 · 날짜를 누르면 저장표로 이동")
