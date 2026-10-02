"""Streamlit page for 평일 주간근무표 (A조 주간 날짜를 고르면 표시)."""
from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from history_ui import day_store_dir, render_trash, store_dir
from night_shift import history_store
from night_shift.day_shift import (
    CONTROL_SLOTS, EDU, EDU_SLOTS, EMERGENCY_KINDS, HALF_DAY_LEAVE, HOURS, NUMBER_COLORS, PATROL, REST, SENIOR_NAMES,
    SHUTTLE, STANDBY, STATUSES, DayPerson,
    day_findings, day_stats, emergency_advisories, emergency_candidates, emergency_events, fill_warnings, load_day,
    load_roster,
    number_people,
    reoptimize_day, save_day, save_roster, solve_day, validate_day,
)

_DAY_GRID = components.declare_component(
    "day_sheet", path=str(Path(__file__).resolve().parent / "night_shift" / "day_grid"))

LOCK_STYLE = ("background-color:#d9d9d9;background-image:repeating-linear-gradient(135deg,rgba(0,0,0,.28) 0 2px,"
              "transparent 2px 7px)")


def roster_path():
    return store_dir() / "day_roster.json"


NIGHT_TEAM = ("만년", "원종", "제욱", "광희", "성호", "준호")   # 야간 근무자 (app.ROSTER와 같은 사람)


def day_role(name: str) -> str:
    """역할: 선임(준호·태환) / 일반(야간 A조 멤버) / 주간고정(그 밖의 주간 고정조)."""
    if name in SENIOR_NAMES:
        return "선임"
    return "일반" if name in NIGHT_TEAM else "주간고정"


WEEKDAYS = "월화수목금토일"


HATCH = "background-image:repeating-linear-gradient(135deg,rgba(0,0,0,.38) 0 2px,transparent 2px 7px);"


def _num_cell(number, text=None, bold=True, hatch=False, pid=None, name="") -> str:
    """번호 칸. data-who = 마우스를 올리면 그 사람 칸 전체 강조, title = 이름 툴팁.
    반차·이탈자는 빗금 위에 흰 바탕 칩으로 숫자를 올려 대비를 지킨다."""
    color = NUMBER_COLORS.get(number, "FFFFFF")
    dark = color == "006699"
    label = escape(text if text is not None else str(number))
    tip = f"{number}번 {name}" + (" (긴급 반차·이탈자)" if hatch else "")
    who = f" data-who='{escape(pid)}'" if pid else ""
    body = f"<span class='chip'>{label}</span>" if hatch else label
    return (f"<td{who} title='{escape(tip)}' style='background-color:#{color};{HATCH if hatch else ''}"
            f"{'color:#fff;' if dark and not hatch else ''}{'font-weight:700;' if bold else ''}'>{body}</td>")


def _who_list(pids, numbers, pname, prefix=()) -> str:
    """대기·휴게·교육 칸의 '7.9.10' 표기를 사람별 span으로 (강조·툴팁용)."""
    items = list(prefix) + [f"<span data-who='{escape(pid)}' title='{numbers[pid]}번 {escape(pname[pid])}'>"
                            f"{numbers[pid]}</span>" for pid in sorted(pids, key=lambda q: numbers[q])]
    return ".".join(items)


STEP_STYLE = ("<style>.steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px;font-size:.85rem}"
              ".steps span{padding:5px 10px;border-radius:999px;background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0}"
              ".steps .now{background:#1d4ed8;color:#fff;border-color:#1d4ed8;font-weight:700}"
              ".steps .done{background:#dcfce7;color:#166534;border-color:#bbf7d0}</style>")


def _steps_html(lock: int | None) -> str:
    """긴급 반차·이탈 3단계 안내 (숨은 클릭 기능을 드러냄)."""
    if lock is None:
        items = [("now", "① LOCK할 시간 고르기 — 왼쪽 파란 시간 칸에서 이미 지나간(진행 중) 마지막 시간을 누르세요"),
                 ("", "② 빠지는 사람 이름 누르기"), ("", "③ 재편성표가 새 탭으로 생김")]
    else:
        items = [("done", f"① {HOURS[lock]}까지 LOCK ✓ (같은 시간을 다시 누르면 취소)"),
                 ("now", "② 빠지는 사람의 이름(노란 칸)을 누르세요"), ("", "③ 재편성표가 새 탭으로 생김")]
    return STEP_STYLE + "<div class='steps'>" + "".join(f"<span class='{c}'>{escape(t)}</span>" for c, t in items) + "</div>"


def day_sheet_html(schedule, team: str = "A", pending_lock: int | None = None, clickable_hours=(),
                   eligible=()) -> str:
    """엑셀 '주간 근무 편성표' 모양: 세로 시간, 가로 포스트, 위쪽 출근자 번호.

    pending_lock / clickable_hours / eligible: 긴급 재편성용 (시간 칸 클릭 → LOCK, 이름 클릭 → 반차·이탈).
    """
    numbers = {p.pid: p.number for p in schedule.people}
    present = sorted((p for p in schedule.people if p.number), key=lambda p: p.number)
    columns = ["G1", "G2", "G3", "L1", "L2", "C1", "C2"]
    # 표는 엑셀 양식처럼 테마와 관계없이 흰 바탕·검은 글자 (다크모드에서 빈칸·대기·휴게 글자가 안 보이던 문제)
    style = ("<style>.dsheet{border-collapse:collapse;width:100%;min-width:720px;table-layout:fixed;"
             "font-size:.9rem;text-align:center;color:#111827;background:#fff}"
             ".dsheet td,.dsheet th{border:1px solid #9ca3af;height:34px;padding:2px;color:#111827;"
             "overflow-wrap:anywhere}.dsheet td{background-color:#fff}"
             ".dsheet th{background-color:#d9d9d9;font-weight:600}.dsheet .title{font-size:1.35rem;"
             "font-weight:800;height:48px}.dsheet .sub{font-size:1.1rem;font-weight:700}"
             ".dsheet .name{font-weight:500}.dsheet .left{text-align:left}"
             ".dsheet .legend{text-align:left;font-size:.78rem;color:#4b5563;height:auto;padding:5px 8px}"
             ".dsheet td.name{height:40px}"
             ".dsheet .chip{background:#fff;color:#111827;padding:0 5px;border-radius:4px}"
             "</style>")
    width = 1 + len(columns) + 1 + 4             # 통제 칸은 항상 (결근이면 빈칸)
    leavers = {p.pid for p in schedule.people if p.leave_from is not None}
    d = schedule.day
    cols = "<colgroup><col style='width:80px'>" + "<col>" * (width - 1) + "</colgroup>"   # 시간 열만 좁게
    parts = [style, f"<div style='overflow-x:auto'><table class='dsheet'>{cols}",
             f"<tr><td class='title' colspan='{width}'>주간 근무 편성표</td></tr>",
             f"<tr><td class='sub' colspan='{width}'>{d.year}년 {d.month:02d}월 {d.day:02d}일 "
             f"{WEEKDAYS[d.weekday()]}요일 근무조 : {team}조</td></tr>"]
    # 출근자 두 줄 (통제A + 번호 순)
    def tag(p):
        leave = f" ({HOURS[p.leave_from]}~×)" if p.leave_from is not None else ""
        return f"{p.number}{p.name}{leave}"
    first = (["통제A"] if schedule.control else []) + [tag(p) for p in present[:5]]
    second = [tag(p) for p in present[5:]]
    span = width - 1
    pids = ([None] if schedule.control else []) + [p.pid for p in present]
    rows_of_pids = (pids[:len(first)], pids[len(first):])
    eligible = set(eligible)

    pname = {p.pid: p.name for p in schedule.people}

    def name_cell(text, pid):
        if pid is None:
            return f"<td class='name'>{escape(text)}</td>"
        hatch = pid in leavers                                           # v1.0: 반차·이탈자 근무자명 칸도 빗금
        style = f" style='{HATCH}'" if hatch else ""
        body = f"<span class='chip'>{escape(text)}</span>" if hatch else escape(text)
        who = f" data-who='{escape(pid)}' tabindex='0'"
        if pending_lock is not None and pid in eligible:
            return (f"<td class='name pick'{who} data-pid='{escape(pid)}' role='button' "
                    f"aria-label='{escape(text)} 반차·이탈 선택' title='눌러서 반차·이탈 선택'{style}>{body}</td>")
        off = " off" if pending_lock is not None else ""
        return f"<td class='name{off}'{who} title='{escape(text)} — 올리면 하루 칸 강조'{style}>{body}</td>"
    for i, names in enumerate((first, second)):
        cells = "".join(name_cell(n, pid) for n, pid in zip(names, rows_of_pids[i]))
        filler = max(0, span - len(names))
        head = f"<th rowspan='2'>근무자명</th>" if i == 0 else ""
        parts.append(f"<tr>{head}{cells}{'<td class=name></td>' * filler}</tr>")
    header = ["근무시간"] + columns + ["통제", "셔틀", "순찰", "대기", "휴게"]
    parts.append("<tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr>")
    for t, hour in enumerate(HOURS):
        column = {pid: row[t] for pid, row in schedule.grid.items()}
        locked = schedule.locked_through is not None and t <= schedule.locked_through
        pending = pending_lock is not None and t <= pending_lock
        attrs = (f" class='hour{' pending' if pending else ''}' data-t='{t}' tabindex='0' role='button' "
                 f"aria-label='{hour}까지 LOCK' title='눌러서 이 시간까지 LOCK (다시 누르면 취소)'"
                 if t in clickable_hours else "")
        if locked:
            cells = [f"<th style='{LOCK_STYLE}' title='LOCK: 기존 배정 유지'>"
                     f"<span class='chip'>{int(hour[:2]):02d}:00 🔒</span></th>"]
        else:
            cells = [f"<th{attrs}>{int(hour[:2]):02d}:00{' 🔒' if pending else ''}</th>"]
        filled = schedule.fill.get(t, {})
        for post in columns:
            who = [pid for pid, label in column.items() if label == post]
            if who:
                cells.append(_num_cell(numbers[who[0]], hatch=who[0] in leavers, pid=who[0], name=pname[who[0]]))
            elif post in filled:                 # §27: 일반근무자로 못 채워 통제A·통제E가 맡은 자리
                tip = "통제A" if filled[post] == "A" else "통제E (편성 밖)"
                cells.append(f"<td title='{tip}: 이 자리를 누군가 채우지 않으면 해가 없음' "
                             f"style='font-weight:800;color:#b91c1c;background:#fee2e2'>{filled[post]}</td>")
            else:
                cells.append("<td></td>")
        cells.append("<td style='font-weight:700'>A</td>" if schedule.control and t in CONTROL_SLOTS else "<td></td>")
        shuttle = schedule.shuttle.get(t)
        cells.append(_num_cell(numbers[shuttle], f"{numbers[shuttle]}({SHUTTLE[t]})", hatch=shuttle in leavers,
                               pid=shuttle, name=pname[shuttle]) if shuttle else "<td></td>")
        patrol = [pid for pid, label in column.items() if label == PATROL]
        a_patrol = schedule.control_patrol == t
        cells.append(_num_cell(numbers[patrol[0]], hatch=patrol[0] in leavers, pid=patrol[0], name=pname[patrol[0]])
                     if patrol else
                     "<td style='font-weight:700'>A</td>" if a_patrol and schedule.control else "<td></td>")
        rest = [pid for pid, label in column.items() if label == REST]
        a_rest = schedule.control and t not in CONTROL_SLOTS and not a_patrol and "A" not in filled.values()
        rest_text = _who_list(rest, numbers, pname, ["A"] if a_rest else [])
        edu = [pid for pid, label in column.items() if label == EDU]
        if t in EDU_SLOTS:
            text = "교육: " + _who_list(edu, numbers, pname) if edu else ""
            cells.append(f"<td colspan='2' class='left'>{text}{(' / 휴게 ' + rest_text) if rest_text else ''}</td>")
        else:
            standby = [pid for pid, label in column.items() if label == STANDBY]
            cells.append(f"<td>{_who_list(standby[:1], numbers, pname)}</td>")
            cells.append(f"<td>{rest_text}</td>")
        parts.append("<tr>" + "".join(cells) + "</tr>")
    legend = ["번호·이름에 마우스를 올리면(누르면 고정) 그 사람의 하루 칸 강조"]   # 표 밑 범례
    if schedule.locked_through is not None or pending_lock is not None:
        legend.append("🔒 빗금 시간 = LOCK (기존 배정 유지)")
    if leavers:
        legend.append("빗금 번호·이름 = 긴급 반차·이탈자")
    if schedule.fill:
        legend.append("<b style='color:#b91c1c'>빨간 A / E</b> = 일반근무자로 못 채워 통제A·통제E가 맡은 자리")
    parts.append(f"<tr><td class='legend' colspan='{width}'>{' · '.join(legend)}</td></tr>")
    parts.append("</table></div>")
    return "".join(parts)


def _summary(schedule) -> None:
    """표 바로 위 판단 요약 (검증 탭·특이사항에 숨어 있던 핵심을 먼저 보여 줌)."""
    errors, advisories = validate_day(schedule), emergency_advisories(schedule)
    fills = [who for posts in schedule.fill.values() for who in posts.values()]
    pills = [(f"⛔ 꼭 지킬 규칙 위반 {len(errors)}건 — 확정 불가", "#FEE2E2", "#991B1B") if errors
             else ("✅ 꼭 지킬 규칙 모두 지킴", "#DCFCE7", "#166534")]
    if advisories:
        pills.append((f"⚠ 가능하면 지킬 규칙 {len(advisories)}건 못 지킴", "#FEF3C7", "#92400E"))
    if fills.count("A"):
        pills.append((f"🅰 통제A가 메운 자리 {fills.count('A')}", "#FEE2E2", "#B91C1C"))
    if fills.count("E"):
        pills.append((f"Ⓔ 통제E가 메운 자리 {fills.count('E')}", "#FEE2E2", "#B91C1C"))
    _pills(pills)


def _show(schedule, key: str, results: list | None = None, seconds: int = 20, view_key: str = "",
          actions=None) -> None:
    """요약 → 표 → 경고 → (확정 등 버튼) → 요약·검증 탭 → 특이사항 순서."""
    _summary(schedule)
    if results is None:
        st.markdown(day_sheet_html(schedule), unsafe_allow_html=True)
    else:
        _lock_sheet(schedule, results, key, seconds, view_key)
    for line in fill_warnings(schedule):                 # §27: 표 밑 작은 경고
        st.caption(f":red[⚠ {line}]")
    if actions:
        actions()
    tab_sum, tab_check = st.tabs(("요약", "검증"))
    with tab_sum:
        stats = pd.DataFrame(day_stats(schedule))
        top = float(stats["포스트"].max()) if not stats.empty else 1.0
        tired = float(stats["피로도"].max()) if not stats.empty else 1.0
        st.dataframe(stats, hide_index=True, width="stretch", column_config={
            "포스트": st.column_config.ProgressColumn("포스트", min_value=0, max_value=top, format="%d"),
            "피로도": st.column_config.ProgressColumn("피로도", min_value=0, max_value=tired, format="%d")})
        st.caption("포스트 = G·L + C (C1/C2도 포스트 1회). 목표: 전일근무자 포스트 횟수 차이 1회 이내. "
                   "피로도 = G1·G2·G3·L1·L2 각 2점, C1·C2·순찰 각 1점, 휴게·대기·교육 0점.")
    with tab_check:
        errors = validate_day(schedule)
        hard_label = ("꼭 지켜야 할 규칙 (긴급 재편성: 근근휴 패턴·G1~L2 채우기)" if schedule.emergency
                      else "꼭 지켜야 할 규칙 (주간 하드룰)")

        def table(rows):                                  # 내용이 먼저, 규칙 번호(룰북 코드)는 뒤에 작게
            frame = pd.DataFrame(rows).rename(columns={"detail": "내용", "rule": "룰북 코드"})
            st.dataframe(frame[["내용", "룰북 코드"]], hide_index=True, width="stretch")
        if errors:
            st.error(f"{hard_label} — 지키지 못한 것 {len(errors)}건. 이대로는 확정할 수 없습니다.")
            table(errors)
        else:
            st.success(f"{hard_label} — 모두 지켰습니다.")
        advisories = emergency_advisories(schedule)
        if advisories:
            st.warning(f"가능하면 지킬 규칙(평소 하드룰) {len(advisories)}건을 못 지켰습니다. "
                       "긴급 재편성이라 확정은 할 수 있습니다.")
            table(advisories)
    st.markdown("#### 📝 특이사항 · 비고")
    for line in day_findings(schedule):
        st.markdown("- " + line.replace("~", "\\~"))


def _choice_label(index: int, schedule) -> str:
    label = f"근무표 {index + 1}"
    info = schedule.emergency
    if info:
        who = next(p for p in schedule.people if p.pid == info["pid"])
        label += f" · 긴급 재편성 ({HOURS[info['start']]}부터, {who.name})"
    return label


def _leavers_text(schedule) -> str:
    """연쇄 재편성까지 누적된 반차·이탈자: '3번 원종 09시~ 긴급 이탈, 2번 성호 13시~ 오후반차'."""
    people = {p.pid: p for p in schedule.people}
    out = []
    for e in emergency_events(schedule):
        p = people[e["pid"]]
        kind = "오후반차" if e["kind"] == EMERGENCY_KINDS[0] else "긴급 이탈"
        out.append(f"{p.number}번 {p.name} {HOURS[e['from']]}~ {kind}")
    return ", ".join(out)


def _emergency_info(schedule) -> None:
    info = schedule.emergency
    if not info:
        return
    st.info(f"긴급 재편성표 · {HOURS[info['start'] - 1]}까지 기존 배정 LOCK · {HOURS[info['start']]}부터 다시 편성  \n"
            f"빠진 사람: {_leavers_text(schedule)}")


def _regenerate_locked(results: list, index: int, seconds: int, view_key: str) -> None:
    """같은 LOCK·같은 반차 조건으로 다른 재편성표를 하나 더 만든다."""
    params = st.session_state.setdefault("day_rebalance_params", {}).get(id(results[index]))
    if not params:
        return
    siblings = [r for r in results if st.session_state["day_rebalance_params"].get(id(r)) == params]
    with st.spinner("LOCK 구간은 그대로 두고 다른 재편성표를 찾는 중입니다…"):
        schedule, status = reoptimize_day(params["base"], params["start"], params["pid"], params["from"],
                                          params["kind"], seconds=seconds, exclude=[r.grid for r in siblings],
                                          seed=len(siblings))
    if schedule is None:
        st.session_state["day_regen_message"] = (
            f"현재 LOCK 조건에서는 이미 만든 {len(siblings)}개와 충분히 다른 재편성표가 더 없습니다. "
            "LOCK 이후 남은 시간이 짧으면 다른 해가 나오기 어렵습니다." if status == "INFEASIBLE"
            else f"재편성표를 만들지 못했습니다 ({status}).")
        return
    st.session_state["day_rebalance_params"][id(schedule)] = params
    results.append(schedule)
    st.session_state[f"{view_key}_pending"] = len(results) - 1
    st.rerun()


def _lock_sheet(base, results: list, key: str, seconds: int, view_key: str = "") -> None:
    """긴급 반차·이탈: 시간 칸 클릭 → 그 시간까지 LOCK(다시 누르면 취소) → 이름 클릭 → 오후반차/이탈 → 바로 재편성."""
    lock_key = f"day_lock_{key}"
    lock = st.session_state.get(lock_key)
    floor = base.locked_through + 1 if base.locked_through is not None else 0
    clickable = list(range(floor, 9))                    # 17시는 LOCK 뒤에 남는 시간이 없어 제외
    if lock is not None and lock not in clickable:
        lock = st.session_state[lock_key] = None
    menus, eligible = {}, set()
    if lock is not None:
        start = lock + 1
        for p in emergency_candidates(base, start):
            options = ([{"label": "오후반차 (13시 퇴근)", "value": "half"}] if start <= HALF_DAY_LEAVE else [])
            options.append({"label": f"긴급 이탈 ({HOURS[start]}부터)", "value": "leave"})
            menus[p.pid] = options
            eligible.add(p.pid)
    if st.session_state.get("day_rb_error"):
        st.error(st.session_state.pop("day_rb_error"))
    html = day_sheet_html(base, pending_lock=lock, clickable_hours=clickable, eligible=eligible)
    if clickable:                                        # 숨은 클릭 기능을 단계 안내로 드러냄
        html = _steps_html(lock) + html
    event = _DAY_GRID(data={"html": html, "menus": menus}, key=f"day_grid_{key}", default=None)
    if not isinstance(event, dict) or not event.get("nonce") or event["nonce"] == st.session_state.get("day_grid_nonce"):
        return
    st.session_state["day_grid_nonce"] = event["nonce"]
    if event.get("kind") == "hour":
        t = int(event["t"])
        st.session_state[lock_key] = None if lock == t else t
        st.rerun()
    if event.get("kind") == "person" and lock is not None and event.get("pid") in eligible:
        start = lock + 1
        half = event.get("choice") == "half" and start <= HALF_DAY_LEAVE
        kind = EMERGENCY_KINDS[0] if half else EMERGENCY_KINDS[1]
        leave_from = HALF_DAY_LEAVE if half else start
        with st.spinner("LOCK 구간은 그대로 두고 남은 시간대를 재편성 중입니다…"):
            schedule, status = reoptimize_day(base, start, event["pid"], leave_from, kind, seconds=seconds)
        if schedule is None:
            st.session_state["day_rb_error"] = (
                "해가 없습니다. 남은 인원으로 근근휴 패턴을 지키면서 G1~L2를 채울 수 없고, "
                "통제A·통제E로 메워도 빈자리가 남습니다(§27)."
                if status == "INFEASIBLE" else f"긴급 재편성표를 만들지 못했습니다 ({status}).")
            st.rerun()
        st.session_state.setdefault("day_rebalance_params", {})[id(schedule)] = {
            "base": base, "start": start, "pid": event["pid"], "from": leave_from, "kind": kind}
        results.append(schedule)
        st.session_state[lock_key] = None
        st.session_state[f"{view_key}_pending"] = len(results) - 1
        st.rerun()


def _tabbed(bases: list, emergencies: list, key: str, base_confirm, emergency_confirm, seconds: int):
    """위쪽 탭: '기존 근무표' | '재편성 1 · 11시~ 이름' | … — 기존 표는 그대로 두고 재편성표를 따로 본다.

    bases: 기존 근무표 후보 (생성본 여러 개 또는 확정본 1개). base_confirm / emergency_confirm: (버튼 글자, 함수) 또는 None.
    Returns the schedule on screen.
    """
    view_key = f"day_view_{key}"
    pending = st.session_state.pop(f"{view_key}_pending", None)
    if pending is not None:
        st.session_state[view_key] = pending
    options = ["base"] + list(range(len(emergencies)))
    if st.session_state.get(view_key) not in options:
        st.session_state[view_key] = "base"

    def label(option):
        if option == "base":
            return "📋 기존 근무표"
        schedule = emergencies[option]
        people = {p.pid: p.name for p in schedule.people}
        names = "·".join(people[e["pid"]] for e in emergency_events(schedule))
        return f"🔒 재편성 {option + 1} · {names} ({HOURS[schedule.emergency['start']]}~)"
    view = "base"
    if emergencies:
        view = st.segmented_control("근무표 보기", options, format_func=label, key=view_key,
                                    label_visibility="collapsed")
        view = "base" if view is None else view
    blocked_help = "꼭 지켜야 할 규칙 위반이 있으면 확정할 수 없습니다 (검증 탭 참고)."
    if view == "base":
        index = 0
        if len(bases) > 1:
            index = st.radio("표시할 근무표", range(len(bases)), format_func=lambda i: f"근무표 {i + 1}",
                             horizontal=True, key=f"{key}_base_pick")
        schedule = bases[index]

        def base_actions():                               # 확정은 표·요약을 본 뒤 판단하는 자리에
            if base_confirm:
                text, action = base_confirm
                blocked = bool(validate_day(schedule))
                if st.button(text, type="primary", key=f"{key}_confirm_base_{index}", disabled=blocked,
                             help=blocked_help if blocked else None):
                    action(schedule)
        _emergency_info(schedule)
        _show(schedule, f"{key}_base_{index}", emergencies, seconds, view_key, actions=base_actions)
        return schedule
    schedule = emergencies[view]

    def emergency_actions():
        c_confirm, c_regen, c_drop = st.columns([2, 2, 1.4])
        with c_confirm:
            text, action = emergency_confirm
            blocked = bool(validate_day(schedule))
            if st.button(text, type="primary", key=f"{key}_confirm_em_{view}", disabled=blocked,
                         help=blocked_help if blocked else None, width="stretch"):
                action(schedule)
        with c_regen:
            if st.button("🔁 같은 LOCK 조건으로 다른 재편성표", key=f"{key}_regen_{view}", width="stretch"):
                _regenerate_locked(emergencies, view, seconds, view_key)
        with c_drop:                                      # 되돌리기: 잘못 만든 재편성 탭 지우기
            if st.button("🗑 이 재편성 버리기", key=f"{key}_drop_{view}", width="stretch"):
                st.session_state.get("day_rebalance_params", {}).pop(id(emergencies[view]), None)
                emergencies.pop(view)
                for k in [k for k in st.session_state if str(k).startswith(f"day_lock_{key}_em_")]:
                    del st.session_state[k]
                st.session_state[f"{view_key}_pending"] = "base"
                st.rerun()
        if st.session_state.get("day_regen_message"):
            st.warning(st.session_state.pop("day_regen_message"))
    _emergency_info(schedule)
    _show(schedule, f"{key}_em_{view}", emergencies, seconds, view_key, actions=emergency_actions)
    return schedule


def render_day_page(shift_date: date, badge) -> None:
    """Sidebar roster + generation, and the main area for one 평일 주간 date."""
    names = load_roster(roster_path())
    with st.sidebar:
        st.subheader("주간 근무자")
        frame = pd.DataFrame({"이름": names, "상태": ["출근"] * len(names), "역할": [day_role(n) for n in names]})
        edited = st.data_editor(   # 야간 표와 같은 모양 (이름·상태·역할). 왼쪽 선택 체크박스 없이 추가만 가능
            frame, num_rows="add", hide_index=True, width="stretch", key=f"day_roster_{shift_date}",
            disabled=("역할",),
            column_config={"상태": st.column_config.SelectboxColumn(options=STATUSES, required=True)})
        rows = [(str(r["이름"]).strip(), r["상태"] or "출근") for _, r in edited.iterrows()
                if str(r["이름"]).strip() not in ("", "None", "nan")]
        new_names = [n for n, _ in rows]
        if new_names != names and len(set(new_names)) == len(new_names):
            save_roster(roster_path(), new_names)
        if len(set(new_names)) != len(new_names):
            st.error("같은 이름이 두 번 있습니다.")
        st.caption("주간 고정조 + A조 명단입니다. 맨 아래 빈 줄에 이름을 쓰면 추가, 이름을 지우면 빠지며 "
                   "다음에도 유지됩니다. 상태(연차·반차)는 이 날짜에만 적용됩니다. 통제는 아래 '통제A 출근'으로 정합니다. "
                   "선임(준호, 예전 태환)은 첫 타임을 휴게·대기·순찰로 시작합니다.")
        control = st.checkbox("통제A 출근", value=True, key=f"day_control_{shift_date}",
                              help="결근이면 통제A 자리만 빈칸이 되고 일반근무자 편성은 그대로입니다.")
        seconds = int(st.number_input("계산 제한시간 (초)", 5, 120, 20, 5, key="day_seconds"))
        generate = st.button("주간 근무표 생성", type="primary", width="stretch", key="day_generate")
        render_trash("day_side")

    people = [DayPerson(n, n, status) for n, status in rows]
    signature = (shift_date.isoformat(), tuple(rows), control)
    if st.session_state.get("day_signature") != signature:
        st.session_state["day_signature"] = signature
        st.session_state["day_results"] = []
        st.session_state["day_emergencies"] = []
        st.session_state["day_error"] = None
    results = st.session_state["day_results"]

    saved = history_store.exists(day_store_dir(), shift_date)
    if saved:
        data = load_day(day_store_dir(), shift_date)
        with badge:
            _pills([("✅ 확정됨", "#DCFCE7", "#166534"), ("☀️ 주간", "#FEF3C7", "#92400E")]
                   + ([("🔒 긴급 재편성", "#DBEAFE", "#1E40AF")] if data["schedule"].emergency else []))
        st.subheader(f"☀️ {shift_date} 주간 근무표 (저장본)")
        st.caption(f"확정 {data['confirmed_at'].replace('T', ' ')}")
        ask = f"day_ask_delete_{shift_date}"
        if st.session_state.get(ask):
            st.warning("이 주간 근무표를 휴지통으로 옮길까요? 언제든 복구할 수 있습니다.")
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("삭제", key=f"day_delete_yes_{shift_date}"):
                history_store.delete_to_trash(day_store_dir(), shift_date)
                st.session_state[ask] = False
                st.rerun()
            if c2.button("취소", key=f"day_delete_no_{shift_date}"):
                st.session_state[ask] = False
                st.rerun()
        elif st.button("🗑 이 날짜 주간 근무표 삭제", key=f"day_delete_{shift_date}"):
            st.session_state[ask] = True
            st.rerun()
        saved_schedule = data["schedule"]
        emergencies = st.session_state.setdefault(f"day_saved_results_{shift_date}", [])

        def replace_saved(schedule):
            history_store.delete_to_trash(day_store_dir(), shift_date)
            save_day(day_store_dir(), schedule, note="긴급 재편성")
            emergencies.clear()
            st.session_state["flash"] = (f"{shift_date} 긴급 재편성표를 확정 저장했습니다. "
                                         "이전 확정본은 휴지통에 있습니다.")
            st.rerun()

        _tabbed([saved_schedule], emergencies, f"saved_{shift_date}", None,
                ("✅ 이 재편성표로 확정 (기존 확정본은 휴지통으로)", replace_saved), seconds)
        return

    if generate and len(set(new_names)) == len(new_names):
        with st.spinner("주간 근무표를 만드는 중입니다…"):
            numbered = number_people(people)
            schedule, status = solve_day(shift_date, numbered, seconds=seconds,
                                         exclude=[r.grid for r in results], seed=len(results), control=control)
        if schedule is None:
            st.session_state["day_error"] = (
                "이전 표들과 충분히 다른 주간 근무표가 더 없습니다." if results and status == "INFEASIBLE"
                else status if "명이라" in status else f"주간 근무표를 만들지 못했습니다 ({status}).")
        else:
            results.append(schedule)
            st.session_state[f"gen_base_pick"] = len(results) - 1
            st.session_state["day_view_gen_pending"] = "base"
            st.session_state["day_error"] = None
    emergencies = st.session_state.setdefault("day_emergencies", [])
    badge_slot = badge
    st.subheader(f"☀️ {shift_date} 평일 주간 근무표")
    if st.session_state.get("day_error"):
        st.error(st.session_state["day_error"])
    if not results:
        with badge_slot:
            _pills([("미생성", "#F1F5F9", "#475569"), ("☀️ 주간", "#FEF3C7", "#92400E")])
        st.info("왼쪽에서 근무자 상태(연차·오전반차·오후반차)를 확인하고 '주간 근무표 생성'을 누르세요. "
                "누를 때마다 다른 근무표가 추가됩니다.")
        return
    def confirm(schedule):
        save_day(day_store_dir(), schedule, note="긴급 재편성" if schedule.emergency else "")
        st.session_state["flash"] = f"{shift_date} 주간 근무표를 확정 저장했습니다."
        st.rerun()

    current = _tabbed(results, emergencies, "gen", ("✅ 이 주간 근무표로 확정", confirm),
                      ("✅ 이 재편성표로 확정", confirm), seconds)
    with badge_slot:
        _pills([("🕓 미확정 (생성만 됨)", "#FEF3C7", "#92400E"), ("☀️ 주간", "#FEF3C7", "#92400E")]
               + ([("🔒 긴급 재편성", "#DBEAFE", "#1E40AF")] if current is not None and current.emergency else []))


def _pills(items) -> None:
    html = "".join(f"<span style='display:inline-block;background:{bg};color:{fg};border-radius:999px;"
                   f"padding:4px 14px;margin:0 8px 6px 0;font-weight:700;font-size:.95rem'>{escape(text)}</span>"
                   for text, bg, fg in items)
    st.markdown(f"<div style='margin:-4px 0 10px'>{html}</div>", unsafe_allow_html=True)
