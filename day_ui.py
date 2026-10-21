"""Streamlit page for 평일 주간근무표 (A조 주간 날짜를 고르면 표시)."""
from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from history_ui import day_store_dir, render_trash, store_dir, upload_saved_label
import mobile_ui
from night_shift import history_store
from night_shift.day_shift import (
    CONTROL_SLOTS, EDU, EDU_SLOTS, EMERGENCY_KINDS, HALF_DAY_LEAVE, HOURS, NUMBER_COLORS, PATROL, REST, SENIOR_NAMES,
    SHUTTLE, STANDBY, STATUSES, TRAINEE, DayPerson, attach_trainees,
    day_findings, day_stats, control_active, emergency_advisories, emergency_candidates, emergency_events, fill_warnings, load_day,
    edit_day, changed_cells, rotation_advisories,
    load_roster,
    number_people,
    reoptimize_day, save_day, save_roster, solve_day, validate_day,
)

_DAY_GRID = components.declare_component(
    "day_sheet", path=str(Path(__file__).resolve().parent / "night_shift" / "day_grid"))
# 폰 근무자 상태 선택표: 야간 근무자와 같은 컴포넌트 (night_shift/roster_picker)
_ROSTER_PICKER = components.declare_component(
    "day_roster_picker", path=str(Path(__file__).resolve().parent / "night_shift" / "roster_picker"))

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


def _joint_style(nums) -> str:
    """여러 번호가 같이 선 칸(공동근무·A와 순찰): 뒤(큰) 번호 색. 번호가 없으면 흰 칸."""
    nums = [n for n in nums if n]
    if not nums:
        return ""
    color = NUMBER_COLORS.get(max(nums), "FFFFFF")
    return f" style='background-color:#{color};font-weight:700{';color:#fff' if color == '006699' else ''}'"


def _cp_cell(text: str, post: str, t: int) -> str:
    """원본 보조 칸(4C·CP·1C). CP 칸은 원본 편성표 CP 색 (CP2 → CP3 → CP1, 2026-10-08)."""
    from night_shift.day_image import cell_number, cp_color
    number = cell_number(text) if post != "CP" else None      # 4C 'A.10' = 10번 색 (원본)
    color = cp_color(text) if post == "CP" else NUMBER_COLORS.get(number) if number else None
    style = f" style='background-color:#{color};font-weight:700'" if color else ""
    return f"<td data-col='{post}' data-t='{t}'{style}>{escape(text)}</td>"


def _shuttle_text_cell(text: str) -> str:
    """업로드 원본의 셔틀 글자('5(해지)')도 번호 색으로 (2026-10-08 사용자 요청). 17시 'CP3'은 CP 색."""
    import re
    from night_shift.day_image import cp_color
    m = re.match(r"\s*(\d{1,2})\s*\(", text)
    if m:
        return _num_cell(int(m[1]), text.strip())
    color = cp_color(text)
    return (f"<td style='background-color:#{color};font-weight:700'>" if color else "<td>") + escape(text) + "</td>"


def _num_cell(number, text=None, bold=True, hatch=False, pid=None, name="", t=None, col=None) -> str:
    """번호 칸. data-who = 마우스를 올리면 그 사람 칸 전체 강조, title = 이름 툴팁.
    반차·이탈자는 빗금 위에 흰 바탕 칩으로 숫자를 올려 대비를 지킨다."""
    color = NUMBER_COLORS.get(number, "FFFFFF")
    dark = color == "006699"
    label = escape(text if text is not None else str(number))
    tip = f"{number}번 {name}" + (" (긴급 반차·이탈자)" if hatch else "")
    who = f" data-who='{escape(pid)}'" if pid else ""
    if t is not None and col is not None:                # 근무 교환(끌기·누르기)용: 몇 시·어느 칸
        who += f" data-t='{t}' data-col='{escape(col)}'"
    body = f"<span class='chip'>{label}</span>" if hatch else label
    return (f"<td{who} title='{escape(tip)}' style='background-color:#{color};{HATCH if hatch else ''}"
            f"{'color:#fff;' if dark and not hatch else ''}{'font-weight:700;' if bold else ''}'>{body}</td>")


def _who_list(pids, numbers, pname, prefix=(), t=None) -> str:
    """대기·휴게·교육 칸의 '7.9.10' 표기를 사람별 span으로 (강조·툴팁용, t가 있으면 근무 교환용 시간)."""
    at = f" data-t='{t}'" if t is not None else ""
    items = list(prefix) + [f"<span data-who='{escape(pid)}'{at} title='{numbers[pid]}번 {escape(pname[pid])}'>"
                            f"{numbers[pid]}</span>" for pid in sorted(pids, key=lambda q: numbers[q])]
    return ".".join(items)


STEP_STYLE = ("<style>.steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px;font-size:.85rem}"
              ".steps span{padding:5px 10px;border-radius:999px;background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0}"
              ".steps .now{background:#1d4ed8;color:#fff;border-color:#1d4ed8;font-weight:700}"
              ".steps .done{background:#dcfce7;color:#166534;border-color:#bbf7d0}"
              "@media(max-width:640px){.steps{gap:3px;font-size:.68rem}"     # 폰: 작은 안내 (2026-10-05)
              ".steps span{padding:2px 7px;border-radius:8px;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere}"
              ".steps .now{font-weight:600}}</style>")


def _steps_html(lock: int | None) -> str:
    """긴급 반차·이탈 3단계 안내 (숨은 클릭 기능을 드러냄)."""
    if lock is None:
        items = [("now", "① LOCK할 시간 고르기 — 왼쪽 파란 시간 칸에서 이미 지나간(진행 중) 마지막 시간을 누르세요"),
                 ("", "② 빠지는 사람 이름 누르기"), ("", "③ 재편성표가 새 탭으로 생김")]
    else:
        items = [("done", f"① {HOURS[lock]}까지 LOCK ✓ (같은 시간을 다시 누르면 취소)"),
                 ("now", "② 빠지는 사람의 이름(노란 칸)을 누르세요"), ("", "③ 재편성표가 새 탭으로 생김")]
    return STEP_STYLE + "<div class='steps'>" + "".join(f"<span class='{c}'>{escape(t)}</span>" for c, t in items) + "</div>"


COMPACT_STYLE = ("<style>.dsheet.compact{min-width:0;font-size:.64rem;line-height:1.15;table-layout:auto}"   # 폰: 가로 스크롤 없이 한 화면
                 ".dsheet.compact td,.dsheet.compact th{height:26px;padding:1px 0}"
                 ".dsheet.compact .title{font-size:1rem;height:30px}.dsheet.compact .sub{font-size:.76rem}"
                 ".dsheet.compact td.name{height:auto;padding:2px 0;font-size:.6rem}"
                 ".dsheet.compact th{font-size:.6rem;font-weight:700;white-space:nowrap;padding:1px}"
                 ".dsheet.compact .chip{padding:0 1px}.dsheet.compact .legend{font-size:.6rem;padding:3px 4px}</style>")


def _break_dots(html: str) -> str:
    """폰 좁은 칸: '1.3.CP1'을 점 뒤에서만 줄바꿈 (CP1이 'CP'·'1'로 쪼개지지 않게). 글자 부분만 바꾼다."""
    import re
    return re.sub(r">([^<]*)<", lambda m: ">" + m[1].replace(".", ".<wbr>") + "<", html)


def day_sheet_html(schedule, team: str = "A", pending_lock: int | None = None, clickable_hours=(),
                   eligible=(), compact: bool = False) -> str:
    """엑셀 '주간 근무 편성표' 모양: 세로 시간, 가로 포스트, 위쪽 출근자 번호.

    pending_lock / clickable_hours / eligible: 긴급 재편성용 (시간 칸 클릭 → LOCK, 이름 클릭 → 반차·이탈).
    compact: 폰 — 야간처럼 가로 스크롤 없이 한 화면에 (2026-10-12 사용자 요청). 글자·칸만 줄이고 내용은 같다.
    """
    if compact:
        html = day_sheet_html(schedule, team, pending_lock, clickable_hours, eligible)
        start = html.index("<div style='overflow-x:auto'>")
        body = html[start:].replace("<table class='dsheet'>", "<table class='dsheet compact'>", 1)
        body = body.replace("<col style='width:80px'>", "<col style='width:36px'>", 1)
        return html[:start] + COMPACT_STYLE + _break_dots(body)
    numbers = {p.pid: p.number for p in schedule.people}
    from night_shift.day_control import control_e_slots
    e_slots = control_e_slots(store_dir(), schedule.day)
    present = sorted((p for p in schedule.people if p.number), key=lambda p: p.number)
    source=schedule.source_layout or {}
    source_rows=source.get('applied_rows',source.get('rows',[]))
    source_mapping=source.get('mapping',{})
    show_source=len(source_rows)==10
    if show_source:
        existing={p.name for p in present}
        listed={**source_mapping,**(source.get('listed') or {})}   # 엑셀 명단 전체: 다른 곳 근무(기타) 인원도 이름 표시 (2026-10-11)
        taken={p.number for p in present}
        present=sorted(present+[DayPerson(n,n,'출근',int(number)) for number,n in listed.items()
                                if number.isdigit() and n not in existing and int(number) not in taken],key=lambda p:p.number)
        numbers.update({p.pid:p.number for p in present})
    columns = ["G1", "G2", "G3", "4C", "L1", "L2", "C1", "C2", "CP", "1C"] if show_source else ["G1", "G2", "G3", "L1", "L2", "C1", "C2"]
    show_control=not show_source
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
    width = 1 + len(columns) + int(show_control) + 4             # 통제 칸은 항상 (결근이면 빈칸)
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
    first = (["통제A"] if schedule.control and not any(p.pid == "A" for p in present) else []) + [tag(p) for p in present[:5]]
    second = [tag(p) for p in present[5:]]
    if e_slots:
        second.append("통제E 최정식")
    # CP 근무자 이름도 명단 칸에 (엑셀 원본처럼 'CP1철룡', 2026-10-11 사용자 요청)
    from night_shift import cp_schedule
    cp_names = {k[2:]: v for k, v in (source.get('extra_names') or {}).items() if k.startswith('CP') and v} \
        or cp_schedule.for_day(store_dir(), schedule.day, "day") or {}
    cp_tags = [f"CP{k}{cp_schedule.short(v)}" for k, v in sorted(cp_names.items())]
    second += cp_tags
    span = width - 1
    pids = ([None] if schedule.control and not any(p.pid == "A" for p in present) else []) + [p.pid for p in present]
    if e_slots:
        pids.append(None)
    pids += [None] * len(cp_tags)
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
    header = ["근무시간"] + columns + (["통제"] if show_control else []) + ["셔틀", "순찰", "대기", "휴게"]
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
        source_row=source_rows[t] if show_source else {}
        for post in columns:
            if post in ('4C','1C','CP'):
                from night_shift.schedule_image_import import normalize_cell as _norm   # 인식 글자 cpl, cp2 → CP1.CP2
                raw_text=str(source_row.get(post,'') or '')
                shown=_norm(raw_text) if raw_text else ''
                cells.append(_cp_cell(shown, post, t))
                continue
            who = [pid for pid, label in column.items() if label == post]
            if who:
                if len(who)==1:
                    cells.append(_num_cell(numbers[who[0]],hatch=who[0] in leavers,pid=who[0],name=pname[who[0]],t=t,col=post))
                else:   # 공동근무 칸은 뒤(큰) 번호 색 (원본 8.11 = 11번 색)
                    cells.append(f"<td data-col='{post}' data-t='{t}'{_joint_style([numbers[w] for w in who])}>"+_who_list(who,numbers,pname,t=t)+"</td>")
            elif post in filled:                 # §27: 일반근무자로 못 채워 통제A·통제E가 맡은 자리
                tip = "통제A" if filled[post] == "A" else "통제E (편성 밖)"
                cells.append(f"<td title='{tip}: 이 자리를 누군가 채우지 않으면 해가 없음' "
                             f"style='font-weight:800;color:#b91c1c;background:#fee2e2'>{filled[post]}</td>")
            else:
                cells.append(f"<td data-col='{post}' data-t='{t}'></td>")
        control_label = "A" if control_active(schedule, t) and t in CONTROL_SLOTS else "E" if t in e_slots else ""
        with_control = [pid for pid, label in column.items() if label == "통제"]   # 통제A와 동행하는 교육 신입
        if show_control:cells.append(f"<td style='font-weight:700'>{_who_list(with_control, numbers, pname, [control_label] if control_label else [], t=t)}</td>"
                                     if control_label or with_control else "<td></td>")
        shuttle = schedule.shuttle.get(t)
        cells.append(_num_cell(numbers[shuttle], f"{numbers[shuttle]}({SHUTTLE[t]})", hatch=shuttle in leavers,
                               pid=shuttle, name=pname[shuttle]) if shuttle else _shuttle_text_cell(str(source_row.get("셔틀",""))))
        patrol = [pid for pid, label in column.items() if label == PATROL]
        from night_shift.day_shift import control_patrol_at
        a_patrol = control_patrol_at(schedule, t)
        if len(patrol)>1 or (patrol and a_patrol):
            cells.append(f"<td data-col='{PATROL}' data-t='{t}'{_joint_style([numbers[w] for w in patrol])}>"+_who_list(patrol,numbers,pname,['A'] if a_patrol else [],t=t)+"</td>")
        else:
            cells.append(_num_cell(numbers[patrol[0]],hatch=patrol[0] in leavers,pid=patrol[0],name=pname[patrol[0]],t=t,col=PATROL) if patrol else "<td style='font-weight:700'>A</td>" if a_patrol and schedule.control else f"<td data-col='{PATROL}' data-t='{t}'></td>")
        rest = [pid for pid, label in column.items() if label == REST]
        a_rest = control_active(schedule, t) and t not in CONTROL_SLOTS and not a_patrol and "A" not in filled.values()
        from night_shift.schedule_image_import import persons,normalize_cell
        import re
        extra_rest=[];extra_edu=[]
        if show_source:
            raw_rest=normalize_cell(str(source_row.get('휴게','')))
            a_rest='A' in persons(raw_rest) and not a_patrol
            extra_rest=[p for p in re.findall(r'CP[123]|[0-9]+',raw_rest) if p.startswith('CP') or (p in source_mapping and source_mapping[p] not in schedule.grid)]
            if raw_rest.startswith('교육'):extra_edu=extra_rest;extra_rest=[]
        rest_text = _who_list(rest, numbers, pname, ["A"] if a_rest else [], t=t)
        if extra_rest:rest_text += ('.' if rest_text else '')+'.'.join(escape(p) for p in extra_rest)
        edu = [pid for pid, label in column.items() if label == EDU]
        if t in EDU_SLOTS:
            text = "교육: " + _who_list(edu, numbers, pname, t=t) if edu else ""
            if extra_edu:text += ("." if text else "교육: ")+".".join(escape(p) for p in extra_edu)
            cells.append(f"<td colspan='2' class='left' data-col='{EDU}' data-t='{t}'>"
                         f"{text}{(' / 휴게 ' + rest_text) if rest_text else ''}</td>")
        else:
            standby = [pid for pid, label in column.items() if label == STANDBY]
            cells.append(f"<td data-col='{STANDBY}' data-t='{t}'>{_who_list(standby, numbers, pname, t=t)}</td>")
            cells.append(f"<td data-col='{REST}' data-t='{t}'>{rest_text}</td>")
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


def _field_record(schedule, key: str) -> str:
    """업로드로 저장한 현장 실제 근무표를 손대지 않고 보는 중이면 '엑셀'/'이미지', 아니면 ''.
    현장 표는 생성 규칙 검사 대상이 아니다 (2026-10-12 사용자 확정). 화면에서 바꾸면 다시 검사."""
    if not (key.startswith("saved_") and "_base_" in key):
        return ""
    if id(schedule) in st.session_state.get("day_originals", {}):
        return ""
    try:
        data = load_day(day_store_dir(), schedule.day)
    except (OSError, ValueError):
        return ""
    source = str(data.get("source", ""))
    if not source.startswith(("excel", "image")) or data.get("final_save_method") == "screen-edit" or data.get("edited_at"):
        return ""
    return "이미지" if source.startswith("image") else "엑셀"


def _summary(schedule, key: str = "") -> None:
    """표 바로 위 판단 요약 (검증 탭·특이사항에 숨어 있던 핵심을 먼저 보여 줌)."""
    kind = _field_record(schedule, key)
    if kind:
        st.caption(f"📥 현장 실제 근무표 ({kind}) — 생성 규칙 검사 대상 아님")
        return
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


def _field_download(schedule, key: str, cp) -> None:
    """주간 현장 양식 이미지 다운로드 — 야간과 같이 업로드 칸 옆 한 곳 (2026-10-07, PC·폰)."""
    import __main__
    from night_shift.day_control import control_e_slots
    from night_shift.day_image import render_day_png
    from night_shift import day_excel_image, day_form_draw
    slot = getattr(__main__, "_DOWNLOAD_SLOT", None)
    with slot if slot is not None else st.container():
        name = f"{schedule.day}_주간근무표.png"
        image = None
        # 원본 편성표 양식 그대로 (엑셀이 그린 빈 양식 + 원본 색 규칙·맑은 고딕, 엑셀 없이 바로) — 2026-10-08
        if day_form_draw.available():
            try:
                spec = day_excel_image.build_spec(schedule, store_dir(), cp)
                labels = {c: k for k, c in day_excel_image.layout()["columns"].items()}
                image = day_form_draw.draw(spec["values"], labels)
            except Exception:
                image = None
        if image is None:                                 # 양식 파일이 없을 때만 예전 그림
            try:
                image = render_day_png(schedule, cp, e_slots=control_e_slots(store_dir(), schedule.day))
            except Exception as exc:                      # 이미지가 안 돼도 화면은 계속
                st.warning(f"주간 근무표 이미지를 만들지 못했습니다: {exc}")
        if image is not None:
            st.download_button("🖼 현장 양식 이미지 다운로드", image, file_name=name, mime="image/png",
                               key=f"day_field_png_{key}", width="stretch")
        try:                                              # 원본 양식 그대로의 엑셀 (2026-10-11, PC·폰)
            book = day_excel_image.to_xlsx(schedule, store_dir(), cp)
            st.download_button("📊 현장 양식 엑셀 다운로드", book, file_name=f"{schedule.day}_주간근무표.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"day_field_xlsx_{key}", width="stretch")
        except Exception as exc:
            st.warning(f"주간 근무표 엑셀을 만들지 못했습니다: {exc}")


def _show(schedule, key: str, results: list | None = None, seconds: int = 20, view_key: str = "",
          actions=None) -> None:
    """표 → 요약 → 경고 → (확정 등 버튼) → 요약·검증 탭 → 특이사항 순서.
    2026-10-13 사용자 요청: 날짜를 누르면 근무표가 맨 먼저 — 표 자리를 먼저 잡고 요약·다운로드는 그 아래."""
    table_area = st.container()
    _summary(schedule, key)
    from night_shift import cp_schedule                 # CP 근무표 기본값 (2026-10-05, PC·폰)
    cp = cp_schedule.for_day(store_dir(), schedule.day, "day")
    _field_download(schedule, key, cp)
    if cp:
        st.caption("🅿️ 주간 CP — " + cp_schedule.caption(cp))
    if st.session_state.get("day_edit_error"):
        st.error(st.session_state.pop("day_edit_error"))
    with table_area:
        if results is None or mobile_ui.is_mobile():          # 폰: 표 칸 클릭 대신 아래 긴급 재편성 입력칸
            compact = mobile_ui.is_mobile()                  # 폰: 야간처럼 가로 스크롤 없이 (2026-10-12)
            if _edit_toggle(key):                            # 폰: 같은 시간 번호 끌기·누르기 (PC 끌기와 같은 교환)
                event = _DAY_GRID(data={"html": day_sheet_html(schedule, compact=compact), "menus": {}, "edit": True},
                                  key=f"day_grid_m_{key}", default=None)
                if isinstance(event, dict) and event.get("nonce") and event["nonce"] != st.session_state.get("day_grid_nonce"):
                    st.session_state["day_grid_nonce"] = event["nonce"]
                    _handle_edit(schedule, event, key)
            else:
                st.markdown(day_sheet_html(schedule, compact=compact), unsafe_allow_html=True)
        else:
            _lock_sheet(schedule, results, key, seconds, view_key)
    if (results is None or mobile_ui.is_mobile()) and results is not None:
        from history_ui import emergency_box              # 접힌 칸을 눌러야 보이는 긴급 반차·이탈 (2026-10-05)
        with emergency_box(f"day_emergency_{key}"):
            _mobile_emergency_form(schedule, results, key, seconds, view_key)
    _trainee_switch(schedule, key)                       # 교육 신입 동행 번호 바꾸기 (PC·폰, 2026-10-07)
    _edit_footer(schedule, key)
    for line in fill_warnings(schedule):                 # §27: 표 밑 작은 경고
        st.caption(f":red[⚠ {line}]")
    if actions:
        actions()
    tab_sum, tab_check = st.tabs(("요약", "검증"))
    with tab_sum:
        stats = pd.DataFrame(day_stats(schedule))
        st.dataframe(stats, hide_index=True, width="stretch", column_config={
            "포스트": st.column_config.NumberColumn("포스트", format="%g"),
            "피로도": st.column_config.NumberColumn("피로도", format="%g")})
        st.caption("포스트 = G·L + C (C1/C2도 포스트 1회). 목표: 전일근무자 포스트 횟수 차이 1회 이내. "
                   "피로도 = G1·G2·G3·L1·L2 각 2점, C1·C2·순찰 각 1점, 휴게·대기·교육 0점.")
    with tab_check:
        _check_tab(schedule, key)
    st.markdown("#### 📝 특이사항 · 비고")
    findings = day_findings(schedule)
    if _field_record(schedule, key):                     # 현장 표는 생성 규칙(포스트 순환) 이탈을 나열하지 않음
        skip = {e["detail"] for e in rotation_advisories(schedule)}
        findings = [f for f in findings if f not in skip and not f.startswith("강한 포스트 순환 권장")]
    for line in findings:
        st.markdown("- " + line.replace("~", "\\~"))


def _check_tab(schedule, key: str) -> None:
    """검증 탭. 업로드한 현장 실제 근무표는 생성 규칙으로 검사하지 않는다 (2026-10-12)."""
    if _field_record(schedule, key):
        st.info("현장 실제 근무표(업로드)는 프로그램 생성 규칙으로 검사하지 않습니다. "
                "표에서 칸을 바꾸면 그때부터 검사합니다.")
        return
    errors = validate_day(schedule)
    hard_label = ("꼭 지켜야 할 규칙 (긴급 재편성: 근근휴·G1~L2·전환 사이 비포스트)" if schedule.emergency
                  else "꼭 지켜야 할 규칙 (주간 하드룰)")

    def table(rows):                                      # 내용이 먼저, 규칙 번호(룰북 코드)는 뒤에 작게
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


def _edit_toggle(key: str) -> bool:
    st.caption("✋ 번호를 꾹 누른 채 같은 시간의 다른 번호로 끌어놓으면 교환됩니다. PC는 마우스로 끌면 됩니다.")
    return True


def _handle_edit(base, event: dict, key: str) -> bool:
    """표 교환 하나 적용. 생성표는 꼭 지킬 규칙을 어기면 거절, 저장본(실제 근무)은 경고만 (야간과 같음)."""
    if event.get("kind") not in ("swap", "move", "rowswap"):
        return False
    saved = key.startswith("saved_") and "_base_" in key   # 저장본 자체(재편성 탭은 생성표처럼 검증)
    try:
        new = edit_day(base, event)
        errors = [] if saved else validate_day(new)
        if errors:
            raise ValueError("꼭 지킬 규칙을 어기게 되어 바꾸지 않았습니다: "
                             + "; ".join(e["detail"] for e in errors[:4]))
    except ValueError as exc:
        st.session_state["day_edit_error"] = str(exc)
        st.rerun()
    st.session_state.setdefault("day_originals", {}).setdefault(
        id(base), ({pid: list(row) for pid, row in base.grid.items()}, dict(base.shuttle), base.people, dict(base.trainees)))
    base.grid, base.shuttle, base.trainees, base.people = new.grid, new.shuttle, new.trainees, new.people
    st.rerun()
    return True


def _edit_footer(base, key: str) -> None:
    """바꾼 칸 수 · 되돌리기 · (저장본) 실제 근무 저장."""
    original = st.session_state.get("day_originals", {}).get(id(base))
    count = changed_cells(original[0], base.grid) if original else 0
    saved = key.startswith("saved_") and "_base_" in key   # 저장본 자체(재편성 탭은 생성표처럼 검증)
    if count:
        st.caption(f"✏️ 표에서 바꾼 칸 {count}개" + ("" if saved else " · 꼭 지킬 규칙은 모두 지킨 상태입니다"))
        if st.button("불러온 저장본으로 되돌리기" if saved else "생성 원본으로 되돌리기", key=f"day_revert_{key}"):
            base.grid, base.shuttle = ({pid: list(row) for pid, row in original[0].items()}, dict(original[1]))
            if len(original) > 2:                        # 이름 끌기로 바뀐 번호·동행도 되돌림
                base.people, base.trainees = original[2], dict(original[3])
            st.session_state["day_originals"].pop(id(base), None)
            st.rerun()
    if saved:
        c1, c2 = st.columns(2)
        from night_shift.source_attachment import render_button   # 원본 보기 = 실제 근무 저장 바로 옆 (2026-10-07)
        render_button(load_day(day_store_dir(), base.day) or {}, f"day-{key}", c2)
        from night_shift.upload_review import revert_button      # 덮어쓰기 전 버전으로 (2026-10-11)
        revert_button(store_dir(), base.day, "day", f"day-{key}", c2)
    if saved and c1.button("💾 실제 근무 저장", key=f"day_save_actual_{key}", type="primary",
                           help="지금 화면의 근무표를 이 날의 최종 실제 근무로 저장합니다 (기존 저장본은 휴지통에 보관)."):
        data = load_day(day_store_dir(), base.day)
        extra = {k: data[k] for k in ("source", "source_hash", "source_sheet", "source_file", "source_review", "source_image", "source_attachment") if k in data}
        extra['final_save_method'] = 'screen-edit'
        note = (data.get("note") or "") + ("\n" if data.get("note") else "") + f"실제 근무 수정 {count}칸" if count else data.get("note", "")
        history_store.delete_to_trash(day_store_dir(), base.day)
        save_day(day_store_dir(), base, note=note, extra=extra)
        st.session_state.get("day_originals", {}).pop(id(base), None)
        st.session_state["flash"] = f"{base.day} 주간 실제 근무를 최종본으로 저장했습니다."
        st.rerun()
    if saved:
        _rename_person_ui(base, key)


def _rename_person_ui(base, key):
    from hashlib import sha256
    from night_shift.day_shift import rename_saved_person
    with st.expander('✏️ 근무자 이름 수정',expanded=False):
        people={p.pid:p for p in base.people}
        if not people:return
        expected=sha256((day_store_dir()/f'{base.day}.json').read_bytes()).hexdigest()
        pid=st.selectbox('수정할 근무자',list(people),format_func=lambda p:f'{people[p].number}번 {people[p].name}',key=f'day_rename_who_{key}')
        name=st.text_input('수정할 이름',value=people[pid].name,key=f'day_rename_name_{key}_{pid}')
        if st.button('💾 이름 수정 저장',type='primary',key=f'day_rename_save_{key}'):
            try:
                rename_saved_person(day_store_dir(),base.day,pid,name,expected)
            except (ValueError,OSError) as exc:
                st.error(str(exc));return
            for cache in list(st.session_state):
                if cache.startswith(f'day_saved_work_{base.day}_'):
                    del st.session_state[cache]
            st.session_state['flash']=f'{base.day} 이름을 {name.strip()}(으)로 수정해 저장했습니다.'
            st.rerun()


def _lock_sheet(base, results: list, key: str, seconds: int, view_key: str = "") -> None:
    """긴급 반차·이탈: 시간 칸 클릭 → 그 시간까지 LOCK(다시 누르면 취소) → 이름 클릭 → 오후반차/이탈 → 바로 재편성."""
    lock_key = f"day_lock_{key}"
    lock = st.session_state.get(lock_key)
    floor = base.locked_through + 1 if base.locked_through is not None else 0
    from history_ui import emergency_toggle              # 눌러야 켜지는 긴급 반차·이탈 (2026-10-05)
    opened = emergency_toggle(f"day_emergency_{key}", force=lock is not None, lock_key=lock_key)
    clickable = list(range(floor, 9)) if opened else []  # 17시는 LOCK 뒤에 남는 시간이 없어 제외
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
    edit = _edit_toggle(key)
    html = day_sheet_html(base, pending_lock=lock, clickable_hours=clickable, eligible=eligible)
    if clickable:                                        # 숨은 클릭 기능을 단계 안내로 드러냄
        html = _steps_html(lock) + html
    event = _DAY_GRID(data={"html": html, "menus": menus, "edit": edit}, key=f"day_grid_{key}", default=None)
    if not isinstance(event, dict) or not event.get("nonce") or event["nonce"] == st.session_state.get("day_grid_nonce"):
        return
    st.session_state["day_grid_nonce"] = event["nonce"]
    if _handle_edit(base, event, key):
        return
    if event.get("kind") == "hour" and opened:
        t = int(event["t"])
        st.session_state[lock_key] = None if lock == t else t
        st.rerun()
    if event.get("kind") == "person" and lock is not None and event.get("pid") in eligible:
        _run_emergency(base, results, lock + 1, event["pid"], event.get("choice") == "half", seconds, view_key,
                       lock_key)


def _run_emergency(base, results: list, start: int, pid: str, half: bool, seconds: int, view_key: str,
                   lock_key: str | None = None) -> None:
    """긴급 반차·이탈 재편성 실행 (PC 표 클릭·폰 입력칸 공통). start 이전은 LOCK."""
    half = half and start <= HALF_DAY_LEAVE
    kind = EMERGENCY_KINDS[0] if half else EMERGENCY_KINDS[1]
    leave_from = HALF_DAY_LEAVE if half else start
    with st.spinner("LOCK 구간은 그대로 두고 남은 시간대를 재편성 중입니다…"):
        schedule, status = reoptimize_day(base, start, pid, leave_from, kind, seconds=seconds)
    if schedule is None:
        st.session_state["day_rb_error"] = (
            "해가 없습니다. 남은 인원으로 근근휴 패턴을 지키면서 G1~L2를 채울 수 없고, "
            "통제A 일반 편입으로도 필수 규칙을 만족하지 못했습니다(§28)."
            if "INFEASIBLE" in status else f"긴급 재편성표를 만들지 못했습니다 ({status}).")
        st.rerun()
    st.session_state.setdefault("day_rebalance_params", {})[id(schedule)] = {
        "base": base, "start": start, "pid": pid, "from": leave_from, "kind": kind}
    results.append(schedule)
    if lock_key:
        st.session_state[lock_key] = None
    st.session_state[f"{view_key}_pending"] = len(results) - 1
    st.rerun()


def _mobile_emergency_form(base, results: list, key: str, seconds: int, view_key: str) -> None:
    """폰 긴급 반차·이탈 (2026-10-03 사용자 요청): 표 칸 클릭 대신 '몇 시까지 진행 → 누가 → 반차/이탈' 입력칸.
    재편성 엔진·LOCK 규칙은 PC와 같다 (_run_emergency)."""
    floor = base.locked_through + 1 if base.locked_through is not None else 0
    hours = list(range(floor, 9))                        # 17시는 LOCK 뒤에 남는 시간이 없어 제외
    if st.session_state.get("day_rb_error"):
        st.error(st.session_state.pop("day_rb_error"))
    if not hours:
        return
    with st.container():              # 바깥 '🚨 긴급 반차·이탈 재편성' 접힌 칸 안에 들어감 (2026-10-05)
        lock = st.selectbox("① 이미 진행된(진행 중) 마지막 시간 — 여기까지 LOCK", hours,
                            format_func=lambda t: f"{HOURS[t]}까지 그대로", key=f"m_lock_{key}")
        start = lock + 1
        candidates = emergency_candidates(base, start)
        if not candidates:
            st.caption("이 시간 이후 빠질 수 있는 근무자가 없습니다.")
            return
        names = {p.pid: f"{p.number}번 {p.name}" if p.number else p.name for p in candidates}
        pid = st.selectbox("② 빠지는 사람", list(names), format_func=names.get, key=f"m_pid_{key}")
        kinds = (["half"] if start <= HALF_DAY_LEAVE else []) + ["leave"]
        labels = {"half": "오후반차 (13시 퇴근)", "leave": f"긴급 이탈 ({HOURS[start]}부터)"}
        choice = st.radio("③ 종류", kinds, format_func=labels.get, horizontal=True, key=f"m_kind_{key}")
        st.caption(f"{HOURS[lock]}까지는 기존 배정을 그대로 두고 {HOURS[start]}부터 다시 편성합니다. 재편성표는 새 탭으로 생깁니다.")
        if st.button("재편성", type="primary", width="stretch", key=f"m_rebalance_{key}"):
            _run_emergency(base, results, start, pid, choice == "half", seconds, view_key)


def request_day_regeneration():
    st.session_state["day_regenerate_requested"] = True


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
                with mobile_ui.action_columns(f"day_{key}_base_{index}") as (c_confirm, c_regen):
                    with c_confirm:
                        if st.button(text, type="primary", key=f"{key}_confirm_base_{index}", disabled=blocked,
                                     help=blocked_help if blocked else None, width="stretch"):
                            action(schedule)
                    with c_regen:
                        st.button("🔁 근무표 재생성", key=f"{key}_regenerate_base_{index}", width="stretch",
                                  on_click=request_day_regeneration)
        _emergency_info(schedule)
        _show(schedule, f"{key}_base_{index}", emergencies, seconds, view_key, actions=base_actions)
        return schedule
    schedule = emergencies[view]

    def emergency_actions():
        mobile = mobile_ui.is_mobile()
        with mobile_ui.action_columns(f"day_{key}_em_{view}", 3 if mobile else [2, 2, 1.4]) as cols:
            c_confirm, c_regen = cols[:2]
            with c_confirm:
                text, action = emergency_confirm
                blocked = bool(validate_day(schedule))
                if st.button(text, type="primary", key=f"{key}_confirm_em_{view}", disabled=blocked,
                             help=blocked_help if blocked else None, width="stretch"):
                    action(schedule)
            with c_regen:
                if st.button("🔁 근무표 재생성", key=f"{key}_regen_{view}", width="stretch"):
                    _regenerate_locked(emergencies, view, seconds, view_key)
            with cols[2]:                                          # 되돌리기: 잘못 만든 재편성 탭 지우기 (PC·폰)
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


def _leave_defaults(day: date, names) -> tuple[dict, list[str], bool]:
    """연차일정 → {이름: (상태, 비고)}, 안내, 통제A 출근 기본값. 화면에서 저장한 기타 비고가 우선."""
    from night_shift import leave_schedule
    defaults, notices = leave_schedule.defaults_for(leave_schedule.load(store_dir(), day.year), day, "day", names)
    for name, note in leave_schedule.load_notes(store_dir()).get(day.isoformat(), {}).get("day", {}).items():
        defaults[name] = ("기타", note)
    manager = defaults.pop("A", None)
    if manager and manager[0] not in ("연차", "기타"):
        notices.append(f"통제A {manager[0]}: 주간 통제는 출근/결근만 있어 출근으로 둡니다. 필요하면 직접 바꾸세요.")
    changed = [f"{n} {s}" + (f"({note})" if note else "") for n, (s, note) in defaults.items()]
    if changed or manager:
        notices.insert(0, "연차일정 반영: " + ", ".join(changed + ([f"통제A {manager[0]}"] if manager else [])))
    return defaults, notices, not (manager and manager[0] in ("연차", "기타"))


def _other_notes_input(day: date, rows, defaults) -> dict:
    """상태 '기타'인 사람마다 짧은 비고 입력칸 (PC·폰 공통). 날짜별로 저장."""
    from night_shift import leave_schedule
    notes = {}
    for name, status in rows:
        if status == "기타":
            notes[name] = st.text_input(f"{name} 기타 비고", value=defaults.get(name, ("", ""))[1],
                                        key=f"day_note_{day}_{name}", placeholder="예: 예비군, 교육, 하계휴가")
    leave_schedule.save_notes(store_dir(), day, "day", notes)
    return notes


def _trainee_input(day: date, rows) -> dict:
    """상태 '교육'(교육받는 신입)마다 동행 대상 선택 (PC·폰 공통). 표를 만든 뒤 표 아래에서도 바꿀 수 있다."""
    trainees = {}
    workers = [n for n, s in rows if s in ("출근", "오전반차", "오후반차")]
    for name, status in rows:
        if status == TRAINEE:
            options = ["동행 없음 (표에서 끌어 붙이기)"] + workers + ["통제A"]
            pick = st.selectbox(f"{name} 동행 대상 (교육)", options, key=f"day_trainee_{day}_{name}",
                                help="교육받는 신입은 마지막 번호를 받습니다. 표에서 이름을 동행할 근무자 이름 칸에 끌어 놓거나 여기서 고르면 "
                                     "그 사람과 같은 칸에 함께 표시됩니다. 룰 검사·편성 인원에서는 빠집니다.")
            trainees[name] = "" if pick == options[0] else "A" if pick == "통제A" else pick
    return trainees


def _trainee_switch(schedule, key: str):
    """생성된 표에서 교육 신입의 동행 번호를 바로 바꾼다 (다시 계산하지 않음)."""
    if not getattr(schedule, "trainees", None):
        return schedule
    numbered = sorted((p for p in schedule.people if p.number and p.pid not in schedule.trainees),
                      key=lambda p: p.number)
    labels = {"": "동행 없음", **{p.pid: f"{p.number}번 {p.name}" for p in numbered}, "A": "통제A"}
    changed = dict(schedule.trainees)
    for pid, companion in schedule.trainees.items():
        number = next((p.number for p in schedule.people if p.pid == pid), "")
        options = list(labels)
        pick = st.selectbox(f"🎓 {number}번 {pid} 동행 번호", options, index=options.index(companion) if companion in options else 0,
                            format_func=labels.get, key=f"{key}_trainee_{pid}_{companion}")   # 끌기로 바뀌면 새 칸
        changed[pid] = pick
    if changed != schedule.trainees:
        updated = attach_trainees(schedule, changed)
        schedule.people, schedule.grid, schedule.trainees = updated.people, updated.grid, updated.trainees
        schedule.rule_exempt_names = updated.rule_exempt_names
        st.rerun()
    return schedule


def render_day_page(shift_date: date, badge, controls=None, mobile: bool = False) -> None:
    """Sidebar roster + generation, and the main area for one 평일 주간 date.

    controls: 조건·생성 칸 (기본 사이드바, 폰은 본문 맨 위 '근무 조건' 칸)."""
    from night_shift.daily_report import retired              # 마지막 근무일이 지난 퇴사자는 편성 명단에서 뺌 (2026-10-12)
    gone = retired(store_dir(), shift_date)
    names = [n for n in load_roster(roster_path()) if n not in gone]
    from night_shift.leave_schedule import refresh_manual_inputs
    refresh_manual_inputs(st.session_state, store_dir(), shift_date, "day")
    defaults, notices, control_default = _leave_defaults(shift_date, names)    # 연차일정 → 기본 상태 (2026-10-04)
    st.session_state.setdefault(f"day_control_{shift_date}", control_default)
    with (controls if controls is not None else st.sidebar):
        st.subheader("주간 근무자")
        if mobile:   # 폰: 야간 근무자와 같은 선택표 (상태 칸을 누르면 연차·반차 선택). 이름 추가·삭제는 아래 접힘 칸
            statuses = st.session_state.setdefault(f"day_statuses_{shift_date}",
                                                   {n: status for n, (status, _) in defaults.items() if n in names})
            event = _ROSTER_PICKER(rows=[{"id": n, "name": n, "status": statuses.get(n, STATUSES[0]),
                                          "role": day_role(n), "locked": False} for n in names],
                                   options=STATUSES, key=f"day_roster_picker_{shift_date}", default=None)
            if isinstance(event, dict) and event.get("nonce") != st.session_state.get("day_roster_nonce"):
                st.session_state["day_roster_nonce"] = event.get("nonce")
                if event.get("employee") in names and event.get("status") in STATUSES:
                    statuses[event["employee"]] = event["status"]
                    st.rerun()
            with st.expander("명단 수정 (이름 추가·삭제)"):
                name_frame = st.data_editor(pd.DataFrame({"이름": names}), num_rows="dynamic", hide_index=True,
                                            width="stretch", key=f"day_names_{shift_date}")
            listed = [str(n).strip() for n in name_frame["이름"] if str(n).strip() not in ("", "None", "nan")]
            rows = [(n, statuses.get(n, STATUSES[0])) for n in listed]
        else:
            frame = pd.DataFrame({"이름": names, "상태": [defaults.get(n, ("출근", ""))[0] for n in names],
                                  "역할": [day_role(n) for n in names]})
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
        st.caption(("상태 칸을 누르면 연차·오전반차·오후반차를 고릅니다. 이름 추가·삭제는 '명단 수정'에서 하며 "
                    if mobile else "주간 고정조 + A조 명단입니다. 맨 아래 빈 줄에 이름을 쓰면 추가, 이름을 지우면 빠지며 ")
                   +
                   "다음에도 유지됩니다. 상태(연차·반차)는 이 날짜에만 적용됩니다. 통제는 아래 '통제A 출근'으로 정합니다. "
                   "선임(준호, 예전 태환)은 첫 타임을 휴게·대기·순찰로 시작합니다.")
        notes = _other_notes_input(shift_date, rows, defaults)
        trainees = _trainee_input(shift_date, rows)
        for line in notices:
            st.caption("📅 " + line)
        control = st.checkbox("통제A 출근", key=f"day_control_{shift_date}",
                              help="결근이면 통제A 자리만 빈칸이 되고 일반근무자 편성은 그대로입니다.")
        seconds = int(st.number_input("계산 제한시간 (초)", 5, 120, 20, 5, key="day_seconds"))
        generate = st.button("주간 근무표 생성", type="primary", width="stretch", key="day_generate")
        if not mobile:
            render_trash("day_side")

    people = [DayPerson(n, n, status, note=notes.get(n, "") if status == "기타" else "") for n, status in rows]
    signature = (shift_date.isoformat(), tuple(rows), control, tuple(sorted(notes.items())), tuple(sorted(trainees.items())))
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
        from night_shift.source_attachment import label as source_label
        st.subheader(f"☀️ {shift_date} 주간 근무표 ({source_label(data)})")
        table_first = st.container()                      # 근무표를 맨 먼저, 원본·삭제 등은 아래 (2026-10-13)
        from image_import_ui import render_saved_image
        render_saved_image(data)
        if "덮어씌워진 근무표" in data.get("note", ""):
            st.info("덮어씌워진 근무표 — 업로드 확인본으로 기존 저장본을 교체했습니다.")
        st.caption(f"확정 {data['confirmed_at'].replace('T', ' ')}")
        ask = f"day_ask_delete_{shift_date}"
        if st.session_state.get(ask):
            st.warning(f"{shift_date} 주간 근무표를 휴지통으로 옮길까요? 화면 아래 휴지통에서 복구할 수 있습니다.")
            c1, c2 = st.columns(2) if mobile else st.columns([1, 1, 4])[:2]
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
        # 표에서 바꾼 내용이 다시 그릴 때 사라지지 않도록 세션에 보관 (저장하면 새 키)
        saved_schedule = st.session_state.setdefault(f"day_saved_work_{shift_date}_{data['confirmed_at']}",
                                                     data["schedule"])
        emergencies = st.session_state.setdefault(f"day_saved_results_{shift_date}", [])

        def replace_saved(schedule):
            history_store.delete_to_trash(day_store_dir(), shift_date)
            save_day(day_store_dir(), schedule, note="긴급 재편성")
            emergencies.clear()
            st.session_state["flash"] = (f"{shift_date} 긴급 재편성표를 확정 저장했습니다. "
                                         "이전 확정본은 휴지통에 있습니다.")
            st.rerun()

        with table_first:
            _tabbed([saved_schedule], emergencies, f"saved_{shift_date}", None,
                    ("✅ 이 재편성표로 확정 (기존 확정본은 휴지통으로)", replace_saved), seconds)
        return

    regenerate_requested = st.session_state.pop("day_regenerate_requested", False)
    if (generate or regenerate_requested) and len(set(new_names)) == len(new_names):
        with st.spinner("주간 근무표를 만드는 중입니다…"):
            numbered = number_people(people)
            schedule, status = solve_day(shift_date, numbered, seconds=seconds,
                                         exclude=[{k: v for k, v in r.grid.items() if k not in r.trainees} for r in results],
                                         seed=len(results), control=control, trainees=trainees)
        if schedule is None:
            st.session_state["day_error"] = (
                "이전 표들과 충분히 다른 주간 근무표가 더 없습니다." if results and status == "INFEASIBLE"
                else status if "명이라" in status else f"주간 근무표를 만들지 못했습니다 ({status}).")
        else:
            results.append(schedule)
            st.session_state[f"gen_base_pick"] = len(results) - 1
            st.session_state["day_view_gen_pending"] = "base"
            st.session_state["day_error"] = None
        if mobile:                                        # 폰: '근무 조건' 칸을 접고 결과부터 보이게
            st.rerun()
    emergencies = st.session_state.setdefault("day_emergencies", [])
    badge_slot = badge
    st.subheader(f"☀️ {shift_date} 평일 주간 근무표")
    if st.session_state.get("day_error"):
        st.error(st.session_state["day_error"])
    if not results:
        with badge_slot:
            _pills([("미생성", "#F1F5F9", "#475569"), ("☀️ 주간", "#FEF3C7", "#92400E")])
        st.info(("위 '근무 조건'에서" if mobile else "왼쪽에서")
                + " 근무자 상태(연차·오전반차·오후반차)를 확인하고 '주간 근무표 생성'을 누르세요. "
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
