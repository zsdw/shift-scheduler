"""Streamlit UI: confirmed history, actual-shift corrections and comparison."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from html import escape
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from night_shift import history_store
from night_shift.actual_edit import (actual_checks, add_state_edit, apply_edits, cell_notes, changed_cells,
                                    describe_edit)
from night_shift.schedule_edit import record_grid_payload
from night_shift.service import calculate_all_stats

def store_dir() -> Path:
    """History folder; NIGHT_SHIFT_HISTORY_DIR overrides it (tests use a temp dir)."""
    override = os.environ.get("NIGHT_SHIFT_HISTORY_DIR")
    return Path(override) if override else Path(__file__).resolve().parent / "history"
HOURS = [f"{(18 + t) % 24:02d}시" for t in range(14)]
STAT_COLUMNS = (("fatigue_value", "피로도"), ("actual_work_time_value", "실근무"),
                ("actual_rest_time_value", "실휴게"), ("standing", "입식"), ("seated", "좌식"),
                ("patrol_count", "순찰"), ("max_rule_work_run", "최장 연속근무"))


def stored_before(shift_date: date) -> list[date]:
    return [d for d in history_store.list_dates(store_dir()) if d < shift_date]


def history_caption(shift_date: date) -> str:
    dates = sorted(stored_before(shift_date), reverse=True)[:4]
    if not dates:
        return "저장된 확정 근무표가 없습니다."
    weights = history_store.cycle_weights(len(dates))
    parts = [f"{d.strftime('%m/%d')} {w * 100:.0f}%" for d, w in zip(dates, weights)]
    return "실제 근무 이력 반영: " + ", ".join(parts) + (" (직전 싸이클 60% : 이전 싸이클 40%)" if len(dates) >= 4
                                                         else " (4회 미만이라 균등)")


def confirm_button(result, key: str) -> None:
    """'이 근무표로 확정' for a valid generated schedule."""
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
                                         rebalance=result.rebalance_info)
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
                                     rebalance=result.rebalance_info)
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
    stores = ((store_dir(), "야간"), (day_store_dir(), "주간"))
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


def _hints(items) -> None:
    chips = "".join(f"<span style='display:inline-block;background:#F1F5F9;border:1px solid #E2E8F0;"
                    f"border-radius:999px;padding:1px 9px;margin:0 6px 4px 0;font-size:.78rem;color:#334155'>{i}</span>"
                    for i in items)
    st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)


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


def _summary_tabs(prefix: str, record, summary_table, summary_detail, baseline_record=None) -> None:
    if summary_table is None or summary_detail is None:
        return
    view = SimpleNamespace(employee_stats=calculate_all_stats(record), record=record)
    baseline = (calculate_all_stats(baseline_record)
                if baseline_record is not None and baseline_record.assignments != record.assignments else None)
    tab_all, tab_person = st.tabs(("전 직원 핵심 비교", "직원 상세분석"))
    with tab_all:
        summary_table(view, heading=False, baseline=baseline, key=f"{prefix}_summary_cols")
    with tab_person:
        summary_detail(view, f"{prefix}_summary_person", heading=False)


def render_history_editor(prefix: str, drag_grid, selected: date,
                          summary_table=None, summary_detail=None) -> None:
    """Stored schedule of one date: first save, latest revision, corrections."""
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

    lock = history_store.locked_through(data)
    if lock >= 0:
        info = data.get("rebalance") or {}
        who = names.get(info.get("employee"), info.get("employee"))
        detail = f" · {who} {HOURS[info['from']]}부터 근무불가 ({info.get('reason', '')})" if info.get("from") is not None else ""
        st.info(_md(f"🔒 긴급 재편성 근무표입니다. 18시~{HOURS[lock]}은 재편성 당시 이미 진행된 시간이라 "
                    f"LOCK(빗금)으로 표시하고 드래그로 바꿀 수 없습니다{detail}."))
    if data.get("source", "").startswith("excel"):
        st.caption("📥 엑셀 근무표에서 옮겨 온 실제 기록입니다. 설명은 아래 특이사항에 있습니다.")
    views = ("최종 수정본", "최초 저장본") if data["edits"] else ("최초 저장본",)
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
        st.markdown(f"#### {selected} 최초 저장본 (읽기 전용)")
        drag_grid(data=record_grid_payload(plan, editable=False, locked_through=lock),
                  key=f"{prefix}_plan_grid_{selected}",
                  default=None)
        _summary_tabs(f"{prefix}_plan", plan, summary_table, summary_detail)
        return {"plan": plan, "actual": actual, "notes": cell_notes(edits), "rebalance": data.get("rebalance"), "lock": lock, "note": data.get("note", ""), "source": data.get("source")}

    notes = cell_notes(edits)
    cell_key = f"{prefix}_cell_{selected}"
    picked = st.session_state.get(cell_key)

    st.markdown(f"#### {selected} 저장본 · 실제 근무 수정")
    _hints(("✋ 칸 끌기 → 실제 근무 교환", "👆 칸 누르기 → 피로도·사유 기록", "📝 누르기 → 주석 보기",
            "빨간 테두리 = 계획과 달라진 칸", "빗금 = LOCK"))
    event = drag_grid(data=record_grid_payload(actual, changed_cells(plan, actual), notes=notes,
                                               cell_click=True, selected_cell=picked, locked_through=lock),
                      key=f"{prefix}_grid_{selected}", default=None)
    nonce_key = f"{prefix}_nonce"
    if isinstance(event, dict) and event.get("nonce") and event["nonce"] != st.session_state.get(nonce_key):
        st.session_state[nonce_key] = event["nonce"]
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
    c1, c2 = st.columns(2)
    if c1.button("💾 실제 근무 저장", key=f"{prefix}_save_{selected}", disabled=saved, type="primary"):
        history_store.save_edits(store_dir(), selected, edits)
        st.success("실제 근무를 저장했습니다. 이후 근무표 생성에 이 실제 기록이 반영됩니다.")
        st.rerun()
    if c2.button("저장본으로 되돌리기", key=f"{prefix}_revert_{selected}", disabled=saved):
        st.session_state[edit_key] = list(data["edits"])
        st.rerun()
    if not saved:
        st.caption("저장하지 않은 수정이 있습니다.")

    _summary_tabs(prefix, actual, summary_table, summary_detail, baseline_record=plan)
    return {"plan": plan, "actual": actual, "notes": notes, "rebalance": data.get("rebalance"), "lock": lock, "note": data.get("note", ""), "source": data.get("source")}


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


def render_monthly(shift_date: date) -> list[dict]:
    """Monthly average fatigue per worker and leave records, from saved actual nights."""
    dates = history_store.list_dates(store_dir())
    if not dates:
        st.info("저장된 근무표가 없습니다. 근무표를 확정 저장하면 월간 피로도와 연차 기록이 여기에 쌓입니다.")
        return []
    months = sorted({(d.year, d.month) for d in dates} | {(shift_date.year, shift_date.month)}, reverse=True)
    year, month = st.selectbox("월 선택", months, format_func=lambda ym: f"{ym[0]}년 {ym[1]}월",
                               key="monthly_month")
    days = [d for d in dates if (d.year, d.month) == (year, month)]
    if not days:
        st.info("이 달에 저장된 근무표가 없습니다. 근무표를 확정 저장하면 여기에 쌓입니다.")
        return []
    totals: dict[str, dict] = {}
    leaves = []
    for day in days:
        record = history_store.actual_record(store_dir(), day)
        names = {e.employee_id: e.name for e in record.context.employees}
        stats = calculate_all_stats(record)
        for a in record.context.attendance:
            label = _leave_label(a, record.context.manager_handover)
            name = "통제" if a.acts_as_manager and a.display_number is None else names[a.employee_id]
            item = totals.setdefault(a.employee_id, {"직원": name, "온전 출근일": 0, "fatigue": 0,
                                                     "work": 0, "연차": 0, "반차": 0})
            if label:
                leaves.append({"날짜": day.strftime("%m/%d"), "직원": name, "구분": label})
                if label in ("연차", "결근"):
                    item["연차"] += 1
                elif "반차" in label:
                    item["반차"] += 1
            person = stats.get(a.employee_id)
            # Averages count only nights worked in full (no 연차·반차·이탈).
            if a.present and label is None and person is not None:
                item["온전 출근일"] += 1
                item["fatigue"] += person.fatigue_value
                item["work"] += person.actual_work_time_value
    rows = []
    for employee_id in sorted(totals, key=lambda p: (p != "A", p)):
        item = totals[employee_id]
        nights = item["온전 출근일"]
        rows.append({**item, "id": employee_id, "is_manager": employee_id == "A", "평균 피로도": round(item["fatigue"] / nights, 2) if nights else None,
                     "평균 실근무": round(item["work"] / nights, 2) if nights else None})
    st.markdown(f"##### {year}년 {month}월 근무자별 피로도 · 저장된 {len(days)}일, 실제 근무 기준")
    st.dataframe(pd.DataFrame(rows)[["직원", "온전 출근일", "평균 피로도", "평균 실근무", "연차", "반차"]],
                 hide_index=True, width="stretch")
    st.caption("평균은 연차·반차·긴급 이탈 없이 온전히 출근한 날만 집계합니다.")
    chart = monthly_dot_chart(rows)
    if chart is not None:
        st.markdown("##### 월간 평균 피로도 (점이 팀 평균선보다 오른쪽이면 부담이 큰 사람)")
        try:
            st.altair_chart(chart, width="stretch")
        except TypeError:  # older Streamlit
            st.altair_chart(chart, use_container_width=True)
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
        if r.barrier_install_flag:
            tokens.append("설치")
        if r.barrier_remove_flag:
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
            + "</div>")


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
