"""PC・폰 공통 주말/공휴일 주간 기본 화면."""
from copy import deepcopy
from html import escape
from pathlib import Path
import pandas as pd
import streamlit as st
from history_ui import day_store_dir, store_dir
from datetime import datetime
from day_ui import (_DAY_GRID, _ROSTER_PICKER, NIGHT_TEAM, WEEKDAYS, HATCH, _num_cell, _leave_defaults,
                    _steps_html)
from night_shift.patrol_history import load_events
from night_shift.weekend_day import (generate, validate, advisories, repeats_of, reoptimize, emergency_candidates,
                                     stats, save, load, leave_text, half_rest_hours, partial_people, LABELS, PATROL, OFF, HALF_DAY_LEAVE, KINDS, STANDBY,
                                     history_debt, emergency_gap, diagnose, display_numbers, display_name, person_label)

STORE = day_store_dir().parent/'weekend_day'
STATUSES = ('출근', '연차', '오전반차', '오후반차', '기타')   # 반차는 평일과 같은 시간 (2026-10-05)

# 평일 주간 '주간 근무 편성표'와 같은 엑셀 양식: 흰 바탕·검은 글자(다크모드 무관), 번호 색 칸
STYLE = ("<style>.wsheet{border-collapse:collapse;width:100%;max-width:880px;min-width:460px;table-layout:fixed;"
         "font-size:.9rem;text-align:center;color:#111827;background:#fff}"
         ".wsheet td,.wsheet th{border:1px solid #9ca3af;height:34px;padding:2px;color:#111827;overflow-wrap:anywhere}"
         ".wsheet td{background-color:#fff}.wsheet th{background-color:#d9d9d9;font-weight:600}"
         ".wsheet .title{font-size:1.35rem;font-weight:800;height:48px}.wsheet .sub{font-size:1.05rem;font-weight:700}"
         ".wsheet td.name{height:38px;font-weight:500}.wsheet .zone{display:block;font-size:.7rem;font-weight:400}"
         ".wsheet .closed{background:#e5e7eb;color:#6b7280;font-size:.78rem}"
         ".wsheet .legend{text-align:left;font-size:.78rem;color:#4b5563;height:auto;padding:5px 8px}"
         # 표 제목 줄 FM·유도리 보기 버튼, 유도리 보기 G2(휴게성) 자홍색 테두리 — 야간과 같은 모양 (2026-10-16)
         ".wsheet .titlebar{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:0 8px}"
         ".wsheet .vbtn{font:inherit;font-size:.85rem;font-weight:700;min-width:64px;min-height:34px;padding:4px 12px;"
         "border:2px solid #94a3b8;border-radius:999px;background:#f1f5f9;color:#334155;cursor:pointer}"
         ".wsheet .vbtn.on{background:#1d4ed8;border-color:#1d4ed8;color:#fff}"
         ".wsheet .vbtn.on.flex{background:#D400FF;border-color:#D400FF}"
         ".wsheet .flexg2{border-left:4px solid #D400FF!important;border-right:4px solid #D400FF!important}"
         ".wsheet th.flexg2{background:#F5D0FE;border-top:4px solid #D400FF!important}"
         ".wsheet td.flexg2.end{border-bottom:4px solid #D400FF!important}</style>")


def _field_download(s, review, key):
    """휴일 주간 현장 양식 이미지·엑셀 다운로드 (2026-10-12, 평일과 같이 업로드 칸 옆, PC·폰).
    review = 업로드 원본 칸(손대지 않은 저장본) → 원본 칸 그대로, 없으면 지금 표로."""
    import __main__
    from datetime import date
    from night_shift import cp_schedule, weekend_form
    slot = getattr(__main__, '_DOWNLOAD_SLOT', None)
    with slot if slot is not None else st.container():
        if not weekend_form.available():
            st.caption('휴일 주간 현장 양식 파일이 없어 다운로드할 수 없습니다.')
            return
        cp = cp_schedule.for_day(store_dir(), date.fromisoformat(str(s.day)), 'day')
        name = f'{s.day}_주간근무표'
        try:
            st.download_button('🖼 현장 양식 이미지 다운로드', weekend_form.draw(s, store_dir(), cp, review),
                               file_name=f'{name}.png', mime='image/png', key=f'wd_png_{key}', width='stretch')
            st.download_button('📊 현장 양식 엑셀 다운로드', weekend_form.to_xlsx(s, store_dir(), cp, review),
                               file_name=f'{name}.xlsx', key=f'wd_xlsx_{key}', width='stretch',
                               mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except Exception as exc:
            st.warning(f'휴일 주간 현장 양식을 만들지 못했습니다: {exc}')


def _saved_review(day):
    """손대지 않은 업로드 저장본이면 원본 칸(source_review), 아니면 None."""
    import json
    try:
        data = json.loads((STORE/f'{day}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if str(data.get('source', '')).startswith(('excel', 'image')) and data.get('final_save_method') != 'screen-edit':
        return data.get('source_review')
    return None


CHANGED = 'box-shadow:inset 0 0 0 3px #dc2626;'          # 저장본과 달라진 칸 (야간 저장본과 같은 빨간 테두리)


def _marks(s, pid, t):
    """칸 주석 표시 '📝' (피로도·사유 기록)."""
    notes = [a for a in s.annotations if a.get('pid') == pid and a.get('t') == t]
    if not notes:
        return ''
    tip = ' / '.join(f"{int(a.get('fatigue', 0)):+d} {a.get('reason', '')}".strip() for a in notes)
    return f"<span title='{escape(tip)}' style='font-size:.7rem'>📝</span>"


def _cell(s, pid, t, col, zone='', changed=frozenset()):
    """번호 칸 (끌어서 교환용 data-who·data-t·data-col). changed: 저장본과 달라진 (사람, 시간)."""
    mark = _marks(s, pid, t)
    number = display_numbers(s)[pid]
    if number == 'A':
        edge = CHANGED if (pid, t) in changed else ''
        return (f"<td data-who='A' data-t='{t}' data-col='{escape(col)}' title='통제A' style='font-weight:800;{edge}'>"
                f"A{mark}{zone}</td>")
    html = _num_cell(int(number), pid=pid, name=display_name(s, pid), t=t, col=col)
    if (pid, t) in changed:
        html = html.replace("style='", f"style='{CHANGED}", 1)
    return html.replace('</td>', f'{mark}{zone}</td>') if zone or mark else html


def sheet_html(s, pending_lock=None, clickable=(), eligible=(), compact=False, changed=frozenset(), view=None):
    """pending_lock·clickable·eligible: 긴급 재편성 (시간 칸 → LOCK, 노란 이름 칸 → 오후반차·이탈).
    compact: 폰 — 평일 주간·야간처럼 가로 스크롤 없이 한 화면에 (2026-10-12).
    changed: 저장본과 달라진 (사람, 시간) — 빨간 테두리 (2026-10-13 실제 근무 수정).
    view: FM 표의 보기 ('FM'·'유도리') — 제목 줄 양옆 버튼, 유도리면 G2 자홍색 테두리 (2026-10-16). None = 버튼 없음."""
    if compact:
        html = sheet_html(s, pending_lock, clickable, eligible, changed=changed, view=view)
        return (html.replace("<table class='wsheet dsheet'>", "<table class='wsheet dsheet compact'>", 1)
                .replace("<col style='width:72px'>", "<col style='width:40px'>", 1)
                + "<style>.wsheet.compact{min-width:0;font-size:.72rem}.wsheet.compact td,.wsheet.compact th"
                  "{height:28px;padding:1px}.wsheet.compact .title{font-size:1rem;height:32px}"
                  ".wsheet.compact .sub{font-size:.78rem}.wsheet.compact td.name{height:auto;font-size:.64rem}"
                  ".wsheet.compact th{font-size:.62rem;white-space:nowrap}.wsheet.compact .zone{font-size:.55rem}"
                  ".wsheet.compact .legend{font-size:.6rem}"
                  ".wsheet.compact .vbtn{font-size:.72rem;min-width:52px;min-height:30px;padding:2px 8px}</style>")
    day = s.day
    try:
        from datetime import date
        d = date.fromisoformat(day)
        day = f"{d.year}년 {d.month:02d}월 {d.day:02d}일 {WEEKDAYS[d.weekday()]}요일"
    except ValueError:
        pass
    # 보안실 대기 열 (2026-10-18): 대기 규칙으로 만든 표·대기 칸이 있는 표만 (원본 휴일 양식 '대기' 열 자리, 순찰 뒤)
    has_sb = getattr(s, 'standby', False) or any(STANDBY in r for r in s.grid.values())
    width = len(LABELS) + 2 + int(has_sb)                  # 근무시간 + 포스트·순찰·(대기)·휴게 + CP 열 (원본 휴일 양식)
    rows = [STYLE, "<div style='overflow-x:auto'><table class='wsheet dsheet'>",
            "<colgroup><col style='width:72px'>" + "<col>" * (width - 1) + "</colgroup>",
            f"<tr><td class='title' colspan='{width}'>" + (
                "주말·공휴일 주간 근무 편성표" if view is None else
                f"<div class='titlebar'><button type='button' class='vbtn{' on' if view != '유도리' else ''}' data-view='FM' "
                "title='FM 기준으로 보기'>FM</button><span>주말·공휴일 주간 근무 편성표</span>"
                f"<button type='button' class='vbtn{' on flex' if view == '유도리' else ''}' data-view='유도리' "
                "title='G2 휴게성(유도리) 기준으로 비교표·비고 보기'>유도리</button></div>") + "</td></tr>",
            f"<tr><td class='sub' colspan='{width}'>{escape(day)} · {escape(('FM 표 · 유도리 보기' if view == '유도리' else s.mode) if g2_open(s) else '결원 2명 (G2 미운영)')}</td></tr>"]
    flex = view == '유도리'
    people = [p for p in s.grid if p != 'A']
    eligible = set(eligible)

    def name_cell(p):
        text = person_label(s, p) + (f" ({leave_text(s, p)})" if leave_text(s, p) else '')
        style = f" style='{HATCH}'" if p in partial_people(s) else ''
        if pending_lock is not None and p in eligible:
            return (f"<td class='name pick' data-who='{escape(p)}' data-pid='{escape(p)}' role='button' "
                    f"title='눌러서 오후반차·긴급 이탈 선택'{style}>{escape(text)}</td>")
        return f"<td class='name' data-who='{escape(p)}'{style}>{escape(text)}</td>"
    # 근무자명 두 줄 (원본 양식처럼): 위 통제A + 번호, 넘치는 번호와 CP는 아랫줄 — 칸이 모자라 6번이 잘리던 문제 (2026-10-12)
    from datetime import date as _date
    from night_shift import cp_schedule
    control = ("통제E" if str(s.names.get('A', '')).startswith('통제E') else
               f"통제A({escape(s.names['A'])})" if '대행' in str(s.names.get('A', '')) else "통제A")
    a_note = f" ({escape(leave_text(s, 'A'))})" if leave_text(s, 'A') else ''      # 통제A 오전·오후반차 (10/18)
    names = ([name_cell('A')] if display_numbers(s).get('A') == '1' else
             [f"<td class='name' style='font-weight:700'>{control}{a_note}</td>"]) + [name_cell(p) for p in people]
    try:
        cps = cp_schedule.for_day(store_dir(), _date.fromisoformat(str(s.day)), 'day')
    except (ValueError, OSError):
        cps = {}
    slots = width - 1
    top, bottom = names[:slots], names[slots:] + [f"<td class='name'>CP{k}{escape(cp_schedule.short(v))}</td>"
                                                  for k, v in sorted(cps.items())]
    pad = lambda cells: "".join(cells[:slots]) + "<td class='name'></td>" * max(0, slots - len(cells))
    rows.append("<tr><th rowspan='2'>근무자명</th>" + pad(top) + "</tr>")
    rows.append("<tr>" + pad(bottom) + "</tr>")
    rows.append("<tr>" + "".join(f"<th{' class=flexg2' if flex and h == 'G2' else ''}>{h}</th>"
                                 for h in ('근무시간',) + LABELS[:4] + ('CP', '순찰') + ((STANDBY,) if has_sb else ())
                                 + ('휴게',)) + "</tr>")
    # CP 시간별 칸: 올린 엑셀의 같은 인원 휴일 형태(없으면 원본 순환), 쉬는 CP는 휴게 칸 뒤 (원본·현장 양식과 같음, 2026-10-13)
    from night_shift.day_image import cp_color
    from night_shift.weekend_form import _cp_hours
    try:
        cp_hours = _cp_hours(store_dir(), _date.fromisoformat(str(s.day)), cps)
    except (ValueError, OSError):
        cp_hours = [""] * 10
    import re as _re
    for t in range(10):
        column = {p: row[t] for p, row in s.grid.items()}
        locked = s.locked_through is not None and t <= s.locked_through
        pending = pending_lock is not None and t <= pending_lock
        if t in clickable:
            cells = [f"<th class='hour{' pending' if pending else ''}' data-t='{t}' tabindex='0' role='button' "
                     f"title='눌러서 이 시간까지 LOCK (다시 누르면 취소)'>{8 + t:02d}:00{' 🔒' if pending else ''}</th>"]
        else:
            cells = [f"<th title='{'LOCK: 기존 배정 유지' if locked else ''}'>{8 + t:02d}:00{' 🔒' if locked else ''}</th>"]
        for post in LABELS[:4]:
            who = [p for p, v in column.items() if v == post]
            if who:
                cell = _cell(s, who[0], t, post, changed=changed)
            elif post == 'G2' and sum(v != OFF for p, v in column.items() if p != 'A') <= 4:
                # 규칙상 G2 미운영인 시간(일반근무자 4명 이하: 결원 2명·긴급)만 '미운영'. 그 밖에 비어 있으면
                # 원본에 사람이 없던 칸이라 빈칸 그대로 — 운영 여부를 추측하지 않는다 (2026-10-13 사용자 지적)
                cell = "<td class='closed'>미운영</td>"
            else:
                cell = f"<td data-t='{t}' data-col='{post}'></td>"
            if flex and post == 'G2':                  # 유도리 보기: G2 휴게성 칸 자홍색 테두리
                mark = 'flexg2' + (' end' if t == 9 else '')
                cell = (cell.replace("<td class='", f"<td class='{mark} ", 1) if cell.startswith("<td class='")
                        else cell.replace('<td', f"<td class='{mark}'", 1))
            cells.append(cell)
        color = cp_color(cp_hours[t]) if cp_hours[t] else None
        cp_style = f" style='background-color:#{color};font-weight:700'" if color else ""
        cells.append(f"<td{cp_style}>{escape(cp_hours[t])}</td>")
        cp_rest = [f"CP{n}" for n in sorted(cps, key=int) if n not in _re.findall(r"CP(\d)", cp_hours[t])]
        who = [p for p, v in column.items() if v == '순찰']
        zone = f"<span class='zone'>{PATROL[t][0]}</span>" if t in PATROL else ''
        cells.append(_cell(s, who[0], t, '순찰', zone, changed) if who else "<td class='closed'></td>")
        if has_sb:
            who = [p for p, v in column.items() if v == STANDBY]
            cells.append(_cell(s, who[0], t, STANDBY, changed=changed) if who
                         else f"<td data-t='{t}' data-col='{STANDBY}'></td>")
        rest = sorted((p for p, v in column.items() if v == '휴게'), key=lambda p: (p != 'A', p))
        off = [p for p, v in column.items() if v == OFF]
        cells.append(f"<td data-t='{t}' data-col='휴게'>" + ".".join(
            f"<span data-who='{escape(p)}' data-t='{t}' title='{escape(person_label(s, p))}'"
            + (" style='outline:2px solid #dc2626;outline-offset:1px'" if (p, t) in changed else '')
            + f">{escape(display_numbers(s)[p])}{_marks(s, p, t)}</span>"
            for p in rest) + (("." if rest else "") + ".".join(cp_rest) if cp_rest else "")
            + (f" <span style='color:#9ca3af' title='반차·이탈 근무불가'>{'.'.join(display_numbers(s)[p] for p in off)}×</span>"
               if off else '') + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    note = ('G2 미운영 · FM·유도리 구분 없음' if not g2_open(s) else
            'FM 표를 유도리로 보기 · <b style="color:#D400FF">자홍색 테두리</b> G2 = 휴게성 · 배정은 그대로' if flex else
            'FM 표 · 같은 배정을 유도리(G2 휴게성)로도 검증' if s.mode == 'FM' else '유도리 표 · G2는 휴게성')
    rows.append(f"<tr><td class='legend' colspan='{width}'>{note} · 순찰 상층·중층 2점, 하층 1점 · "
                "같은 시간의 두 번호를 끌어서(폰은 꾹 눌러 끌거나 차례로 눌러서) 교환</td></tr>")
    return "".join(rows) + "</table></div>"


def g2_open(s):
    """결원 2명(일반 4명 + 통제A)이면 G2 미운영."""
    return len(s.grid) > 5


def views_of(s):
    """비교·n빵 판정에 쓰는 기준. G2 미운영이면 FM·유도리가 같아 하나만."""
    if not g2_open(s):
        return ('FM',)
    return ('FM', '유도리') if s.mode == 'FM' else ('유도리',)


def nbbang_text(s, status=None):
    """완벽한 n빵(통제A 제외 일반근무자 실근무·피로도 차이 0) 여부. status: 생성 당시 Solver 결과."""
    views = views_of(s)
    gaps = []
    for view in views:          # 끝까지 근무하는 일반근무자끼리 (긴급 반차·이탈자 제외)
        rows = [r for p, r in zip(s.grid, stats(s, view)) if p != 'A' and p not in partial_people(s)]
        gaps += [f"{view} 실근무 {max(r['실근무'] for r in rows)-min(r['실근무'] for r in rows)}시간·"
                 f"피로도 {max(r['피로도'] for r in rows)-min(r['피로도'] for r in rows)}점"]
    if all(' 0시간·' in g and g.endswith(' 0점') for g in gaps) and not s.leavers:
        return '⚖️ **완벽한 n빵** — 통제A' + (' ·반차자' if s.half_days else '') + \
               ' 제외 일반근무자 실근무·피로도가 모두 같습니다' + (' (FM·유도리 양쪽)' if len(views) == 2 else '') + '.'
    if s.leavers or s.half_days:
        head = '긴급 재편성' if s.leavers else '반차일 편성'
        allowed = (' (피로도 격차 1 우선, 불가능 확인 시에만 2 허용)' if s.leavers else '')
        over = ('  \n피로도 격차 1 이내의 해가 없음을 확인해 2 이내로 편성했습니다.'
                if status == 'EMERGENCY_GAP_2' else
                '  \n⚠️ 현재 표는 새 격차 기준의 단계 검증을 받지 않았습니다. 재생성해 주세요.'
                if s.leavers and status not in ('EMERGENCY_GAP_1', 'EMERGENCY_GAP_2') else '')
        return (f"⚖️ **{head}** — 반차·이탈자를 뺀 일반근무자끼리 비교합니다"
                + (" (이 조건에서 최선 확인)" if status == 'OPTIMAL' else '') + allowed + ". 격차: " + ' / '.join(gaps)
                + over
                + ('  \n⚠️ 평소 하드룰을 모두 지키는 표가 없어 연속 실근무 상한·격차 1을 가능하면 지킬 규칙으로 낮췄습니다.'
                   if s.relaxed else ''))
    why = ('완벽한 n빵은 지금 규칙으로 불가능함을 계산으로 확인해 1 차이 표를 만들었습니다'
           if status in ('OPTIMAL', 'NO_PERFECT') else
           '계산 시간 안에 더 고른 표를 찾지 못했습니다(불가능 확인은 아님)' if status else '화면에서 교환한 표입니다')
    return f"⚖️ **1 차이 표** — {why}. 일반근무자 격차: " + ' / '.join(gaps)   # 이력·4연속은 특이사항에


def _notes(s, field, view=None, tables=True):
    """tables: 순찰·막타임 표도 여기에 (폰). PC는 비고가 표 오른쪽 좁은 칸이라 표는 근무표 아래 전체 폭에 따로."""
    st.markdown('#### 📝 특이사항 · 비고')                # 평일·야간과 같은 내용 (2026-10-13 사용자 요청)
    if view == '유도리':
        st.caption('🟣 유도리 기준 숫자입니다(배정은 같음, G2는 휴게성 회계).')
    for line in weekend_notes(s, field, view):
        st.markdown('- ' + line.replace('~', '\\~'))
    if tables:
        _cycle_tables(s, view)


def _cycle_tables(s, view=None):
    try:                                              # 야간과 이어 보는 순찰·막타임 표 (2026-10-18 사용자 요청)
        duties = recent_duties(s)
    except Exception as exc:                          # 표 하나 때문에 화면 전체가 멈추지 않게
        st.caption(f'순찰·막타임 표를 만들지 못했습니다: {exc}')
        return
    st.markdown('**순찰 싸이클 (최근 6근무 · 야간 + 빨간날 주간)**')
    st.markdown(cycle_patrol_html(duties), unsafe_allow_html=True)
    st.markdown('**막타임 휴게 (야간 07시 · 빨간날 주간 17시)**')
    st.markdown(cycle_last_rest_html(duties, view), unsafe_allow_html=True)


HOLIDAY_BG = '#FEF08A'                                # 빨간날 주간 칸 노란 배경 (야간과 구분, 2026-10-18 사용자 요청)

# 지난 빨간날 주간 FM 표를 실제로 유도리로 운영했는지 (2026-10-18 사용자 요청). 고르지 않으면 '유도리 했음'이 기본값.
# 유도리였던 날은 17시 G2(휴게성)도 막타임 수혜로 보고 다음 근무표 순번·직전 수혜 판단에 쓴다. 저장본 파일은 건드리지 않는다.
FLEX_FILE = STORE / 'flex_actual.json'


def _flex_choices():
    import json
    try:
        return json.loads(FLEX_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def flex_actual(iso):
    """그날 실제 유도리 운영 여부 (선택 없으면 True = 유도리 했음)."""
    return _flex_choices().get(str(iso)[:10], {}).get('mode', '유도리') == '유도리'


def set_flex_actual(iso, mode):
    import json
    data = _flex_choices()
    data[str(iso)[:10]] = {'mode': mode, 'at': datetime.now().isoformat(timespec='seconds')}
    FLEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLEX_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(FLEX_FILE)


def _flex_relevant(s):
    """유도리 여부가 막타임에 영향을 주는 표: FM으로 만든 G2 운영일 표에서 17시 G2를 선 일반근무자가 있음."""
    return s.mode == 'FM' and g2_open(s) and any(p != 'A' and r[9] == 'G2' for p, r in s.grid.items())


def flex_confirm_banner(today=None):
    """근무표 화면 맨 위: 최근 14일 안 지난 빨간날 주간(FM 표) 중 유도리 운영 여부를 아직 고르지 않은 날 (최대 3개).
    더 오래된 날은 그 날짜 저장본 화면의 '이날 실제 운영'에서 바꾼다 (고르지 않으면 유도리)."""
    from datetime import date as _date, timedelta
    today = today or _date.today()
    chosen = _flex_choices()
    pending = []
    for path in sorted(STORE.glob('????-??-??.json'), reverse=True):
        d = _date.fromisoformat(path.stem)
        if d >= today or path.stem in chosen:
            continue
        if d < today - timedelta(days=14):
            break
        try:
            s = load(STORE, path.stem)
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if _flex_relevant(s):
            pending.append((d, s))
        if len(pending) >= 3:
            break
    for d, s in pending:
        who = '·'.join(s.names[p] for p, r in s.grid.items() if p != 'A' and r[9] == 'G2')
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.markdown(f"🟣 **{d:%m/%d}({'월화수목금토일'[d.weekday()]}) 빨간날 주간** — 유도리로 운영했나요? "
                    f"17시 G2 {who} 막타임 여부가 달라져요 · 고르지 않으면 **유도리 했음**으로 계산")
        if c2.button('유도리 했음', key=f'flex_yes_{d}', width='stretch'):
            set_flex_actual(d, '유도리'); st.rerun()
        if c3.button('FM으로 함', key=f'flex_no_{d}', width='stretch'):
            set_flex_actual(d, 'FM'); st.rerun()


def _who(name):
    from night_shift.patrol_history import key
    return key(name)


def _weekend_duty(s, label, now=False, actual_flex=False):
    """주말 주간 표 한 장 → 사람(이름 끝 2글자)별 순찰 구역·출근 여부, 17시(막타임) 실휴게 받은 일반근무자.
    actual_flex: 지난날을 실제 유도리로 운영(기본값) → FM 표 17시 G2도 막타임 수혜로 셈."""
    people, rest, flex = {}, set(), set()
    for pid, row in s.grid.items():
        if not any(v not in (None, OFF) for v in row):
            continue
        who = 'A' if pid == 'A' else _who(s.names[pid])
        people[who] = [PATROL[t][0] for t, v in enumerate(row) if v == '순찰']
        last = row[9]
        if pid != 'A' and (last in ('휴게', STANDBY) or (s.mode == '유도리' and last == 'G2')):
            rest.add(who)
        elif pid != 'A' and s.mode == 'FM' and last == 'G2':
            flex.add(who)                             # FM 표 17시 G2: 유도리로 보면 휴게성 막타임 (2026-10-18)
    names = {('A' if p == 'A' else _who(n)): ('통제' if p == 'A' else n) for p, n in s.names.items()}
    counted = bool(actual_flex and flex and not now)
    return {'label': label, 'holiday': True, 'now': now, 'people': people, 'rest': rest | flex if counted else rest,
            'flex_rest': flex, 'flex_counted': counted, 'names': names}


def recent_duties(s, limit=6):
    """이 빨간날 주간 전 실제 근무 최근 limit개(저장된 야간 + 빨간날 주간, 시간순) + 이번 표.
    같은 날이면 주간(08~18시)이 그날 야간(18시~)보다 먼저."""
    from datetime import date as _date
    day = _date.fromisoformat(str(s.day)[:10])
    return past_duties(day, limit) + [_weekend_duty(s, f'이번 {day:%m/%d}', now=True)]


def last_rest_input(day, names):
    """주말 엔진에 넘길 막타임 이력 (2026-10-18, 야간 07시·빨간날 주간 17시를 이어서): 오늘 출근자 번호별
    {'prev': 직전 실제 출근에 받음, 'last': 마지막으로 받은 날 ordinal(없으면 -1)}. 통제A 제외."""
    from datetime import date as _date
    from night_shift import history_store
    from history_ui import store_dir
    day = _date.fromisoformat(str(day)[:10])
    duties = past_duties(day, limit=len(history_store.list_dates(store_dir())) + len(list(STORE.glob('*.json'))) + 1)
    out = {}
    for pid, name in names.items():
        if pid == 'A':
            continue
        who = _who(name)
        attended = [d for d in duties if who in d['people']]
        got = [d['ordinal'] for d in attended if who in d['rest']]
        out[pid] = {'prev': bool(attended) and who in attended[-1]['rest'], 'last': max(got) if got else -1}
    return out


def past_duties(day, limit=6):
    """day 전 실제 근무 최근 limit개 (저장된 야간 + 빨간날 주간, 시간순)."""
    from datetime import date as _date
    from history_ui import store_dir, _last_rest_people
    from night_shift import history_store
    from night_shift.calendar_info import is_off_day
    zone = {'upper': '상층', 'middle': '중층', 'lower': '하층'}
    items = []
    for r in history_store.recent_actuals(store_dir(), day, limit=limit):
        d = r.context.shift_start_date
        names = {e.employee_id: e.name for e in r.context.employees}
        people = {}
        for a in r.context.attendance:
            if a.present:
                people['A' if a.employee_id == 'A' else _who(names[a.employee_id])] = []
        for a in sorted(r.assignments, key=lambda a: a.slot.index):
            if a.actual_post_or_work_type.kind.value == 'patrol':
                who = 'A' if a.employee_id == 'A' else _who(names[a.employee_id])
                people.setdefault(who, []).append(zone.get(a.actual_post_or_work_type.label,
                                                           a.actual_post_or_work_type.label))
        _, rest_ids = _last_rest_people(r)
        items.append(((d, 1), {'label': f'{d:%m/%d}', 'holiday': False, 'now': False, 'people': people,
                               'ordinal': d.toordinal() * 2 + 1,
                               'rest': {_who(names[p]) for p in rest_ids},
                               'names': {('A' if p == 'A' else _who(n)): ('통제' if p == 'A' else n)
                                         for p, n in names.items()}}))
    for path in STORE.glob('????-??-??.json'):
        d = _date.fromisoformat(path.stem)
        if d < day and is_off_day(d):
            try:
                duty = _weekend_duty(load(STORE, path.stem), f'{d:%m/%d}주', actual_flex=flex_actual(path.stem))
            except (OSError, ValueError, TypeError, KeyError):
                continue
            duty['ordinal'] = d.toordinal() * 2              # 같은 날 주간이 야간보다 먼저
            items.append(((d, 0), duty))
    return [v for _, v in sorted(items, key=lambda kv: kv[0])][-limit:]


_CYCLE_CSS = ("<style>.wcycle{border-collapse:separate;border-spacing:0;width:100%;font-size:.8rem;table-layout:fixed}"
              ".wcycle th{font-weight:600;color:#475569;padding:5px 2px;border-bottom:1px solid #e2e8f0;text-align:center;"
              "white-space:nowrap;font-size:.74rem}.wcycle th:first-child{width:3.4em}"
              ".wcycle td{padding:4px 2px;border-bottom:1px solid #f1f5f9;text-align:center;overflow-wrap:anywhere}"
              ".wcycle td.name{text-align:left;font-weight:600;white-space:nowrap}"
              f".wcycle .hol{{background:{HOLIDAY_BG}}}.wcycle .now{{box-shadow:inset 0 0 0 2px #94a3b8}}"
              ".wcycle .muted{color:#cbd5e1}.wcycle .off{color:#94a3b8;font-size:.7rem}"
              ".wcycle .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:2px}</style>")


def _cycle_rows(duties, generals_only):
    names = {}
    for d in duties:
        names.update(d['names'])
    current = duties[-1]['names']                     # 이번 표 사람 순서 (통제 먼저)
    order = [p for p in current if not (generals_only and p == 'A')]
    order += [p for p in names if p not in order and not (generals_only and p == 'A')]
    return names, order


def _cycle_head(duties):
    return "<th>직원</th>" + "".join(
        f"<th class='{'hol' if d['holiday'] else ''}{' now' if d['now'] else ''}'"
        f" title='{'빨간날 주간' if d['holiday'] else '야간'}'>{escape(d['label'])}</th>" for d in duties)


def cycle_patrol_html(duties):
    """사람 × 최근 근무(야간 + 빨간날 주간) 순찰 구역. 빨간날 주간 칸은 노란 배경. 오른쪽 상·중·하 횟수(이번 제외)."""
    from history_ui import ZONE_COLORS, PAPER
    names, order = _cycle_rows(duties, False)
    rows = []
    for p in order:
        cells = [f"<td class='name'>{escape(names[p])}</td>"]
        counts = {'상층': 0, '중층': 0, '하층': 0}
        for d in duties:
            cls = ''                                   # 노란색·이번 테두리는 날짜(머리글) 칸에만 (2026-10-18 사용자 요청)
            if p not in d['people']:
                cells.append(f"<td class='off {cls}'>결근</td>")
                continue
            zones = d['people'][p]
            if not d['now']:
                for z in zones:
                    counts[z] = counts.get(z, 0) + 1
            cells.append(f"<td class='{cls}'>" + (''.join(
                f"<span title='{z} 순찰'><span class='dot' style='background:{ZONE_COLORS.get(z, '#94a3b8')}'>"
                f"</span>{z[0]}</span>" for z in zones) or "<span class='muted'>·</span>") + "</td>")
        cells += [f"<td>{counts[z]}</td>" for z in ('상층', '중층', '하층')]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = _cycle_head(duties) + "<th>상</th><th>중</th><th>하</th>"
    legend = (f"<div style='font-size:.72rem;color:#475569;margin-top:4px'>"
              f"<span style='background:{HOLIDAY_BG};padding:0 6px;border-radius:3px'>노란 날짜</span> = 빨간날 주간 · "
              "흰 날짜 = 야간 ·상·중·하 = 최근 6근무 횟수(이번 제외) · 차단봉은 야간만</div>")
    return (_CYCLE_CSS + f"<div style='{PAPER}'><table class='wcycle'><tr>{head}</tr>{''.join(rows)}</table>"
            + legend + "</div><div style='height:12px'></div>")


def cycle_last_rest_html(duties, view=None):
    """막타임 휴게(야간 07시·빨간날 주간 17시 실휴게)를 이어서: 일반근무자 × 최근 근무, 🛌 = 받음. 통제A 제외.
    view='유도리'(표 제목 줄 유도리 보기): FM으로 만든 빨간날 주간 표의 17시 G2도 휴게성이라 '🛌(유도리)' (2026-10-18)."""
    from history_ui import PAPER
    names, order = _cycle_rows(duties, True)
    rows, prev, repeats = [], set(), []
    for d in duties:                                   # 직전 출근에 이어 또 받은 경우
        repeats += [f"{d['label']} {names.get(p, p)}" for p in d['rest'] if p in prev]
        prev = (prev - set(d['people'])) | set(d['rest'])
    for p in order:
        cells = [f"<td class='name'>{escape(names[p])}</td>"]
        for d in duties:
            cls = ''                                   # 노란색·이번 테두리는 날짜(머리글) 칸에만
            # 🛌(유도리): FM 표 17시 G2 — 이번 표는 항상 표시, 지난날은 실제 유도리 운영(기본값)일 때만 (10/18)
            flexed = p in d.get('flex_rest', ()) and (d['now'] or d.get('flex_counted'))
            mark = ("🛌<span style='font-size:.68rem;color:#a21caf'>(유도리)</span>" if flexed else
                    '🛌' if p in d['rest'] else
                    '' if p in d['people'] else "<span class='off'>결근</span>")
            cells.append(f"<td class='{cls}'>{mark}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    past = {p: sum(p in d['rest'] for d in duties[:-1]) for p in order}
    gap = max(past.values()) - min(past.values()) if past else 0
    verdict = (f"최근 6근무 수혜 횟수 차이 {gap}회 · "
               + ("직전 출근에 이어 또 받은 사람 없음" if not repeats else "연속 수혜: " + ", ".join(repeats)))
    return (_CYCLE_CSS + f"<div style='font-size:.82rem;margin:2px 0 4px'>{escape(verdict)}</div>"
            + f"<div style='{PAPER}'><table class='wcycle'><tr>{_cycle_head(duties)}</tr>{''.join(rows)}</table>"
            + f"<div style='font-size:.72rem;color:#475569;margin-top:4px'><span style='background:{HOLIDAY_BG};"
            "padding:0 6px;border-radius:3px'>노란 날짜</span> = 빨간날 주간(17시) · 흰 날짜 = 야간(07시)"
            + " · 🛌(유도리) = FM 표 17시 G2(유도리면 휴게성 — 지난날은 실제 유도리 운영일 때만 수혜로 셈, 기본 유도리)</div>"
            + "</div><div style='height:12px'></div>")


def weekend_notes(s, field=False, view=None):
    """주말 주간 특이사항·비고 (2026-10-13). field = 업로드한 현장 표를 그대로 보는 중(원본 메모만 덧붙임).
    view: 표 제목 줄 FM·유도리 보기 — 점수(실근무·피로도) 줄만 그 기준으로 (2026-10-16)."""
    import json
    lines = []
    from datetime import date as _date                     # 💒 웨딩 있는 날 (연차일정 탭 입력, 표기만)
    from history_ui import store_dir
    from night_shift import wedding
    try:
        if wedding.has(store_dir(), _date.fromisoformat(str(s.day)[:10])):
            lines.append('💒 웨딩 있는 날 (연차일정 탭에서 입력)')
    except ValueError:
        pass
    control = person_label(s, 'A')
    name = lambda p: person_label(s, p)
    proxy = getattr(s, 'proxy', None) if getattr(s, 'a_half', None) else None
    off = [f"{name(p)} {leave_text(s, p)}" for p in s.grid if leave_text(s, p) and p not in ('A', proxy)]
    if off:
        lines.append('반차·이탈: ' + ', '.join(off))
    if proxy:                                          # 통제A 미리 정한 반차 (2026-10-18)
        lines.append(f"통제A {s.a_half}: " + (
            f"08~12시 {name(proxy)}가 통제A 패턴(08시 {s.grid[proxy][0]} · 09시 {s.grid[proxy][1]}, G1 제외), 13시부터 통제A"
            if s.a_half == '오전반차' else
            f"13시 퇴근 · {name(proxy)}가 마지막 2시간 규칙 계승(16시 {s.grid[proxy][8]} · 17시 {s.grid[proxy][9]})"))
    elif '대행' in str(s.names.get('A', '')):
        lines.append(f"통제A 연차: {control} (나머지 근무자 기준 결원 1명 더)")
    if not g2_open(s):
        lines.append('결원 2명: G2 미운영 (FM·유도리 같음)')
    a = s.grid['A']
    view = view or ('FM' if s.mode == 'FM' else '유도리')
    a_stat = next(r for p, r in zip(s.grid, stats(s, view)) if p == 'A')
    lines.append(f"{control}: 09시 {a[1]} · 16시 {a[8]} · 17시 {a[9]} · 실근무 {a_stat['실근무']}시간 · 피로도 {a_stat['피로도']}점"
                 + f" · 포스트 {', '.join(v for v in LABELS[:4] if v in a) or '없음'}")
    patrol = [f"{8 + t}시 {PATROL[t][0]} {name(p)}" for t in sorted(PATROL) for p, row in s.grid.items() if row[t] == '순찰']
    if patrol:
        lines.append('순찰: ' + ' · '.join(patrol))
    for pid,person in s.names.items():
        if pid=='A':continue
        events=[e for e in s.patrol_events if e['name']==person[-2:]]
        if '순찰' in s.grid.get(pid,[]) and any(e['excluded'] for e in events[-2:]):
            lines.append(f'{name(pid)}: 순찰 제외 후 야간·공휴일 주간 출근 2회 보호로 순찰 배정')
        elif events and '순찰' not in s.grid.get(pid,[]) and any(v not in (None,OFF) for v in s.grid.get(pid,[])):
            lines.append(f'{name(pid)}: 이번 순찰 제외 · 이전 야간·공휴일 주간 제외 {sum(e["excluded"] for e in events)}회')
    for a in s.annotations:                            # 실제 근무 피로도·사유 기록 (2026-10-13)
        lines.append(f"📝 {8 + a['t']:02d}시 {name(a['pid'])} 피로도 {int(a.get('fatigue', 0)):+d} {a.get('reason', '')}".rstrip())
    extra = (history_text(s, view) + long_run_text(s, (view,) if g2_open(s) and s.mode == 'FM' else None)
             ).replace('  \n', '\n').strip()
    lines += [x for x in extra.split('\n') if x and not field]
    if field:
        try:
            note = json.loads((STORE / f'{s.day}.json').read_text(encoding='utf-8')).get('note', '')
        except (OSError, ValueError):
            note = ''
        for x in (x.strip() for x in note.split('\n') if x.strip()):
            if x.startswith('엑셀 편성표 일괄 가져오기:'):      # 파일 이름(저장용 해시)은 빼고 시트 이름만
                lines.append(f"원본: 엑셀 {x.split(' / ')[-1]} 시트")
            else:
                lines.append(f'원본 메모: {x}')
    return lines


def long_run_text(s, views=None):
    """결원 1명 시간 4연속 실근무 안내 (2026-10-12: 4연속 없이 해가 없을 때만 최소로 사용). views: 보는 기준만."""
    found = []
    for view in views or views_of(s):
        for p, row in s.grid.items():
            run = 0
            for t, label in enumerate(row):
                run = 0 if label in ('휴게', STANDBY, OFF) or (view == '유도리' and label == 'G2') else run + 1
                if run == 4:
                    who = person_label(s, p)
                    found.append(f"{view} {who} {8 + t - 3}~{8 + t + 1}시")
    if not found:
        return ''
    return ('  \n🔁 4연속 실근무 ' + str(len(found)) + '건 — 4연속 없이는 표가 나오지 않아 가장 적게 사용: '
            + ' · '.join(found))


def history_text(s, view=None):
    """완벽 n빵이 안 된 날: 최근 주말 주간 이력의 손해 점수와 오늘 피로도 (2026-10-12). view: 보는 기준."""
    debt, days = history_debt(STORE, s.day)
    full = [p for p in s.grid if p != 'A' and p not in partial_people(s)]
    if not days or not full:
        return '  \n📜 최근 주말 주간 이력이 없어 이력 어드밴티지는 적용하지 않았습니다.'
    view = view or ('FM' if s.mode == 'FM' else '유도리')
    today = {p: r['피로도'] for p, r in zip(s.grid, stats(s, view))}
    order = sorted(full, key=lambda p: -debt.get(s.names[p], 0))
    parts = [f"{person_label(s, p)} {debt.get(s.names[p], 0):+.1f}→{today[p]}점" for p in order]
    span = f"{days[-1][5:].replace('-', '/')}~{days[0][5:].replace('-', '/')} {len(days)}회"
    return (f"  \n📜 최근 주말 주간 {span} 손해 피로도(+ 많이 함) → 오늘 피로도({view}): " + ' · '.join(parts)
            + " — 남는 차이는 손해 본 사람이 덜 받게 (n빵·2연속 다음 순위)")


def _roster_input(day, mobile):
    """야간 근무자 표와 같은 이름·상태·역할 표 (PC 표 편집, 폰 선택표). 연차일정이 기본값."""
    from night_shift.leave_schedule import refresh_manual_inputs
    refresh_manual_inputs(st.session_state, store_dir(), day, "weekend")
    defaults, notices, control_default = _leave_defaults(day, list(NIGHT_TEAM))
    initial = {}
    for name in NIGHT_TEAM:
        status = defaults.get(name, ('출근', ''))[0]
        if status not in STATUSES:
            notices.append(f"{name} {status}: 알 수 없는 상태라 출근으로 두었습니다. 직접 확인하세요.")
            status = '출근'
        initial[name] = status
    role = lambda n: '선임' if n == '준호' else '일반'
    st.subheader('주간 근무자')
    if mobile:
        statuses = st.session_state.setdefault(f'wd_statuses_{day}', dict(initial))
        event = _ROSTER_PICKER(rows=[{'id': n, 'name': n, 'status': statuses[n], 'role': role(n), 'locked': False}
                                     for n in NIGHT_TEAM], options=STATUSES, key=f'wd_roster_picker_{day}', default=None)
        if isinstance(event, dict) and event.get('nonce') != st.session_state.get('wd_roster_nonce'):
            st.session_state['wd_roster_nonce'] = event.get('nonce')
            if event.get('employee') in statuses and event.get('status') in STATUSES:
                statuses[event['employee']] = event['status']
                st.rerun()
    else:
        edited = st.data_editor(
            pd.DataFrame([{'이름': n, '상태': initial[n], '역할': role(n)} for n in NIGHT_TEAM]),
            hide_index=True, num_rows='fixed', width='stretch', disabled=('이름', '역할'), key=f'wd_roster_{day}',
            column_config={'상태': st.column_config.SelectboxColumn(options=STATUSES, required=True)})
        statuses = {r['이름']: (r['상태'] or '출근') for _, r in edited.iterrows()}
    for line in notices:
        if not line.startswith('통제A '):            # 통제A 반차 안내는 아래 통제A 상태 칸이 대신함
            st.caption('📅 ' + line)
    # 통제A 상태 (2026-10-18 사용자 확정): 오전·오후반차·연차면 준호가 통제A 역할을 계승 (미리 정한 반차·연차)
    from night_shift import leave_schedule
    a_entry = leave_schedule.defaults_for(leave_schedule.load(store_dir(), day.year), day, 'day',
                                          list(NIGHT_TEAM))[0].get('A')
    a_default = (a_entry[0] if a_entry and a_entry[0] in ('오전반차', '오후반차') else
                 '연차(준호 대행)' if a_entry or not control_default else '출근')
    key = f'wd_a_status_{day}'
    if key not in st.session_state:
        st.session_state[key] = a_default
    control = st.radio('통제A 상태', CONTROL_STATUSES, horizontal=True, key=key,
                       help='오전반차: 08~12시 준호가 통제A 패턴(08시 휴게·G2, 09시 G1 제외) · '
                            '오후반차: 준호가 16시 휴게(권장)·17시 휴게 계승 · 연차: 준호가 통제A 자리')
    if a_entry:
        st.caption(f"📅 연차일정: 통제A {a_entry[0]}")
    st.caption('상태에서 연차·오전반차(13시 출근)·오후반차(13시 퇴근)·기타(근무 제외)를 고릅니다.')
    out = {n: statuses.get(n, '출근') or '출근' for n in NIGHT_TEAM}
    out['A'] = control
    return out


CONTROL_STATUSES = ('출근', '오전반차', '오후반차', '연차(준호 대행)')
PROXY_NAME = '준호'                                  # 통제A 대행 (야간과 같은 선임, 2026-10-18 사용자 확정)


def render_weekend_day_page(day, badge, controls=None, mobile=False):
    from history_ui import store_dir
    from night_shift import wedding
    is_wedding = wedding.has(store_dir(), day)          # 💒 연차일정 탭에서 직접 입력 (2026-10-13, 표기만)
    badge.info('주말·공휴일 주간 · 기본 편성' + (' · 💒 웨딩 있음' if is_wedding else ''))
    if is_wedding:
        st.markdown("<div style='display:inline-block;background:#FCE7F3;color:#9D174D;border:1px solid #F9A8D4;"
                    f"border-radius:999px;padding:4px 14px;margin:0 0 8px;font-weight:700'>💒 {day:%m/%d} 웨딩 있는 날</div>",
                    unsafe_allow_html=True)
    table_first = st.container()        # 날짜를 누르면 근무표가 맨 먼저, 안내·버튼은 아래 (2026-10-13 사용자 요청)
    st.info('통제A 출근·일반 결원 0~2명 기본틀입니다. 오전·오후반차와 긴급 오후반차·이탈 재편성을 지원합니다. '
            '관리자대행·과거 이력 보정은 아직 적용하지 않습니다.')
    with controls if controls is not None else st.sidebar:
        statuses = _roster_input(day, mobile)
        control = statuses.pop('A', '출근')
        a_half = control if control in ('오전반차', '오후반차') else None
        if control != '출근' and statuses.get(PROXY_NAME) != '출근':
            st.error(f'통제A {control}: 대행할 {PROXY_NAME}이(가) 하루 전체 출근이 아니라 자동 편성할 수 없습니다. 수기로 편성하세요.')
            return
        if control.startswith('연차'):                # 준호가 통제A 자리 → 나머지 기준 결원 1명 더 (10/18 사용자 확정)
            statuses[PROXY_NAME] = '대행'
        absent = [n for n, v in statuses.items() if v in ('연차', '기타', '대행')]
        if len(absent) == 2:      # G2 미운영 → FM·유도리 차이가 없어 고를 필요 없음
            mode = 'FM'
            st.caption('결원 2명: G2를 운영하지 않아 FM·유도리 구분이 없습니다.')
        else:
            mode = st.radio('공휴일 주간 운영 모드', ('FM','유도리'), horizontal=True, key='wd_mode')
        # 2026-10-05 사용자 확정(고정 하드): G2 최대 2회·3연속 입식 금지·일반 실근무 1시간/피로도 1점 이내,
        # 통제A 실근무 ≤ 일반근무자(야간과 동일)·통제A 17시 휴게
        cap, balance, standing, priority = 2, True, True, True
        clicked = st.button('공휴일 주간 근무표 생성', type='primary', key='wd_generate')
        if not mobile:                                # PC 사이드바 휴지통 (폰은 화면 맨 아래 공통 휴지통, 2026-10-18)
            from history_ui import render_trash
            render_trash('wd_side')
    names = {'A': f'{PROXY_NAME} 대행' if control.startswith('연차') else '통제A',
             **{str(i):name for i,name in enumerate(NIGHT_TEAM,1) if name not in absent}}
    half_days = {str(i): statuses[name] for i, name in enumerate(NIGHT_TEAM, 1)
                 if statuses[name] in ('오전반차', '오후반차')}
    proxy = next((p for p, n in names.items() if n == PROXY_NAME), None) if a_half else None
    signature = (str(day), tuple(names.items()), tuple(half_days.items()), mode, cap, balance, standing, priority,
                 a_half)
    cands_key, idx_key = f'wd_cands_{day}', f'wd_cand_{day}'    # 생성 후보들 (2026-10-18, 야간처럼 재생성마다 쌓음)
    st.session_state['wd_cand_keys'] = (cands_key, idx_key)
    if st.session_state.get('wd_signature') != signature:
        st.session_state['wd_signature'] = signature
        st.session_state.pop('wd_schedule', None)
        st.session_state.pop(f'wd_em_{day}', None)
        st.session_state.pop(cands_key, None)
        st.session_state.pop(idx_key, None)
    if len(absent) > 2:
        st.error('기본틀은 결원 0~2명까지 지원합니다.'); return
    st.caption('08~18시 · 결원 2명은 G2 미운영 · 순찰 상→중→하 / 상→중→하 (2·2·1점) · '
               'G2 1인 최대 2회 · 3연속 입식 금지 · 일반근무자 실근무 1시간·피로도 1점 이내 · '
               '통제A 실근무 ≤ 일반근무자 · 통제A 09시 첫 순찰·포스트마다 1번·16시 휴게 권장(안 되면 G2, 결원 2명이면 G1 외)·17시 휴게 · 전 근무자 3연속 휴게 금지(유도리 G2 포함) · 일반근무자 운영 포스트마다 최소 1번 · '
               + ('FM 생성은 같은 표를 FM·유도리 양쪽으로 검증합니다.' if mode == 'FM' else '유도리 생성은 유도리 기준으로 검증합니다.'))
    key = f'wd_{day}'
    if (STORE/f'{day}.json').exists():
        import json
        from image_import_ui import render_saved_image
        render_saved_image(json.loads((STORE/f'{day}.json').read_text(encoding='utf-8')))
        # 저장본은 날짜를 고르면 바로 표시 (불러오기 버튼 없음, 평일·야간과 같음 — 2026-10-13 사용자 요청)
        current = st.session_state.get('wd_schedule')
        showing_saved = current is not None and id(current) == st.session_state.get('wd_saved_id')
        if current is None or (not showing_saved and st.button('↩ 저장된 근무표 다시 보기', key=key + '_load')):
            saved = st.session_state['wd_schedule'] = load(STORE, day)
            st.session_state['wd_saved_id'] = id(saved)
            # 실제 근무 수정 기준 (2026-10-13): 저장본 칸·주석. 이 표에서 바꾼 칸은 빨간 테두리, '💾 실제 근무 저장'
            st.session_state['wd_editing_saved'] = str(day)
            st.session_state['wd_saved_grid'] = {p: list(r) for p, r in saved.grid.items()}
            st.session_state['wd_saved_ann'] = [dict(a) for a in saved.annotations]
            data = json.loads((STORE/f'{day}.json').read_text(encoding='utf-8'))
            source = str(data.get('source', ''))      # 업로드한 현장 표는 생성 규칙 검사 대상 아님 (2026-10-12)
            st.session_state['wd_field'] = ((id(saved), '이미지' if source.startswith('image') else '엑셀')
                                            if source.startswith(('excel', 'image'))
                                            and data.get('final_save_method') != 'screen-edit' else None)
            st.session_state['wd_status'] = None
            st.session_state.pop(f'wd_em_{day}', None)
            st.session_state[idx_key] = None
            if current is not None:
                st.rerun()
    current = st.session_state.get('wd_schedule')
    cands = st.session_state.setdefault(cands_key, [])
    # 표 아래 '🔁 근무표 재생성' (2026-10-18): 이전 후보들과 모두 다른 표를 새 후보로 추가
    regenerate = st.session_state.pop('wd_regen_req', None) == str(day) and current is not None
    if clicked or regenerate:
        history, events = history_debt(STORE, day)[0], load_events(store_dir(), day, 'day')
        rests = last_rest_input(day, names)            # 막타임 이력: 야간 07시와 이어서 (2026-10-18)
        avoid = [c['schedule'].grid for c in cands] + [current.grid] if regenerate else None
        with st.spinner('공휴일 주간표를 계산하고 검증합니다 (최대 1분)…'):
            result, status = generate(day, names, mode, g2_cap=cap, balance=balance,
                                      standing_limit=standing, manager_priority=priority, half_days=half_days,
                                      exclude=avoid, history=history, patrol_events=events, last_rest=rests,
                                      a_half=a_half, proxy=proxy)
        if result is None:
            st.error('반차로 일반근무자가 3명인 시간이 생깁니다. 주말 주간 룰북 지원 범위 밖이라 수기로 편성하세요.'
                     if status == 'UNSUPPORTED' else
                     ('이전 후보와 다른 표가 더 없습니다. ' if regenerate else '') +
                     '선택한 조건을 모두 만족하는 해가 없습니다. 조건을 자동으로 완화하지 않았습니다.' if status == 'INFEASIBLE'
                     else f'시간 안에 해를 찾지 못했습니다 ({status}). 불가능 판정은 아닙니다.')
            if status != 'UNSUPPORTED' and not regenerate:     # 해 없음 원인 안내 (2026-10-18, 진단만·자동 적용 없음)
                with st.spinner('어떤 규칙 때문에 표가 안 나오는지 확인 중입니다 (최대 1분)…'):
                    found = diagnose(day, names, mode, half_days=half_days, history=history, patrol_events=events,
                                     last_rest=rests, a_half=a_half, proxy=proxy)
                if found:
                    st.warning('🔎 원인 안내 — 아래 규칙 하나만 빼면 표가 나옵니다(진단일 뿐 자동 적용하지 않습니다):  \n'
                               + '  \n'.join('· ' + f for f in found))
                else:
                    st.warning('🔎 원인 안내 — 규칙 묶음을 하나씩 빼 봐도 표가 나오지 않았습니다. '
                               '여러 규칙이 함께 막고 있거나 인원·반차 조건이 지원 범위를 벗어납니다.')
        else:
            if not regenerate:
                cands.clear()
            cands.append({'schedule': result, 'status': status, 'initial': deepcopy(result)})
            st.session_state[idx_key] = len(cands) - 1
            st.session_state['wd_schedule'] = result
            st.session_state['wd_status'] = status
            st.session_state['wd_editing_saved'] = None        # 새 생성표는 실제 근무 수정 대상 아님
            st.session_state.pop(f'wd_em_{day}', None)
            if (STORE/f'{day}.json').exists() or regenerate:   # 저장본 날짜: 위쪽 '↩ 저장된 근무표 다시 보기' 버튼이 보이게
                st.rerun()
    base = st.session_state.get('wd_schedule')
    if base is None:
        _records(day)
        return
    results = st.session_state.setdefault(f'wd_em_{day}', [])     # 긴급 재편성표들: {'schedule','status'}
    view_key = f'wd_view_{day}'
    pending = st.session_state.pop(view_key + '_pending', None)
    if pending is not None:
        st.session_state[view_key] = pending
    options = ['base'] + list(range(len(results)))
    if st.session_state.get(view_key) not in options:
        st.session_state[view_key] = 'base'
    view = 'base'
    idx = st.session_state.get(idx_key)
    with table_first:
        if idx is not None and len(cands) > 1:          # 생성 후보 고르기 (야간 '표시할 근무표'와 같음)
            def cand_label(i):
                c = cands[i]
                mark = ' ✏️' if c['schedule'].grid != c['initial'].grid or c['schedule'].annotations else ''
                return f"후보 {i + 1}" + (' · 완벽 n빵' if c['status'] == 'OPTIMAL' else '') + mark
            pick = st.radio('표시할 근무표', range(len(cands)), index=idx, format_func=cand_label, horizontal=True,
                            key=f'wd_candpick_{day}_{len(cands)}_{idx}')
            if pick != idx:
                _select_candidate(day, pick)
                st.rerun()
        if results:
            def label(o):
                if o == 'base':
                    return '📋 기존 근무표'
                r = results[o]['schedule']
                who = '·'.join(r.names[p] for p in r.leavers)
                return f"🔒 재편성 {o + 1} · {who} ({8 + r.locked_through + 1}시~)"
            view = st.segmented_control('근무표 보기', options, format_func=label, key=view_key,
                                        label_visibility='collapsed')
            view = 'base' if view is None else view
        if view == 'base':
            _show(base, key, st.session_state.get('wd_status'), results, view_key, mobile, None)
        else:
            _show(results[view]['schedule'], f'{key}_em{view}', results[view]['status'], results, view_key, mobile, view)
        if idx is not None and len(cands) > 1 and view == 'base':     # 이전에 생성한 근무표 (펼쳐 비교·선택)
            st.markdown('#### 이전에 생성한 근무표')
            for i, c in enumerate(cands):
                if i == idx:
                    continue
                with st.expander(f'후보 {i + 1}', expanded=False):
                    if st.button('이 근무표 선택', key=f'wd_pick_{day}_{i}'):
                        _select_candidate(day, i)
                        st.rerun()
                    st.markdown(sheet_html(c['schedule'], compact=mobile), unsafe_allow_html=True)
    _records(day)


def _select_candidate(day, i):
    """생성 후보 i를 화면 표로 (교환으로 바꾼 내용은 후보마다 그대로 보관)."""
    c = st.session_state[f'wd_cands_{day}'][i]
    st.session_state[f'wd_cand_{day}'] = i
    st.session_state['wd_schedule'] = c['schedule']
    st.session_state['wd_status'] = c['status']
    st.session_state.pop(f'wd_em_{day}', None)


def _records(day):
    """저장된 주말 주간 실제 근무 기록 (2026-10-13 사용자 요청): 날짜별 사람 피로도(실근무)와 최근 4회 손해 점수.
    이력 어드밴티지(history_debt)가 보는 자료를 그대로 보여 준다. 평일·야간 기록과 섞지 않는다."""
    import json
    days = sorted(p.stem for p in STORE.glob('????-??-??.json'))
    if not days:
        return
    with st.expander(f'📊 주말 주간 기록 · 저장된 {len(days)}일', expanded=False):
        table, notes = {}, []
        for iso in days:
            try:
                s = load(STORE, iso)
                data = json.loads((STORE / f'{iso}.json').read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                continue
            view = 'FM' if s.mode == 'FM' else '유도리'
            col = iso[5:].replace('-', '/')
            for p, r in zip(s.grid, stats(s, view)):
                who = display_name(s, p) if p != 'A' or display_numbers(s).get(p) == '1' else '통제A'
                part = f" ({leave_text(s, p)})" if leave_text(s, p) else ''
                table.setdefault(who, {})[col] = f"{r['피로도']}점·{r['실근무']}h{part}"
            source = '엑셀 원본' if str(data.get('source', '')).startswith(('excel', 'image')) else '프로그램 생성'
            if data.get('final_save_method') == 'screen-edit':
                source += '·실제 수정'
            notes.append(f"{col} {source} · {'통제E 지원' if str(s.names.get('A', '')).startswith('통제E') else '통제A'}")
        debt, used = history_debt(STORE, str(day))
        frame = pd.DataFrame.from_dict(table, orient='index').fillna('')
        frame.insert(0, '최근 4회 손해', [f"{debt[n]:+.1f}" if n in debt else '' for n in frame.index])
        st.dataframe(frame, use_container_width=True)
        st.caption('칸 = 피로도·실근무(그날 모드 기준). 최근 4회 손해 = 일반근무자 평균보다 피로도를 많이 한 합 (+는 손해 → '
                   f'n빵이 안 되는 날 덜 받음, 기준 {", ".join(d[5:].replace("-", "/") for d in used) or "없음"}) · '
                   + ' · '.join(notes))


EDIT_LABELS = ('G1', 'G2', 'I1', 'L1', '순찰', STANDBY, '휴게', OFF)


def _actual_editor(s, slot, key, changed, dirty):
    """저장된 주말 주간 실제 근무 수정 (2026-10-13 사용자 요청, 야간 저장본과 같은 흐름. PC·폰 공통).
    표에서 같은 시간 두 번호 끌기(폰: 꾹 눌러 끌기) = 교환. 교환으로 안 되는 변경(쉬었음·빠짐 등)과 피로도·사유는 아래 칸."""
    from night_shift.weekend_day import save_actual
    st.caption('✋ 같은 시간 두 번호 끌기 = 실제 근무 교환 · 빨간 테두리 = 저장본과 달라진 칸 · 📝 = 피로도·사유 기록')
    with st.expander('✏️ 칸 직접 수정 · 피로도·사유 기록', expanded=False):
        people = list(s.grid)
        label = lambda p: person_label(s, p)
        with st.form(key + '_actual_form'):
            c1, c2 = st.columns(2)
            t = c1.selectbox('시간', range(10), format_func=lambda t: f'{8 + t:02d}시', key=key + '_ae_t')
            pid = c2.selectbox('사람', people, format_func=label, key=key + '_ae_p')
            c3, c4 = st.columns(2)
            work = c3.selectbox('실제 업무', ('그대로',) + EDIT_LABELS,
                                format_func=lambda v: '근무불가(×)' if v == OFF else v, key=key + '_ae_v')
            fatigue = c4.number_input('피로도 가감', -3, 3, 0, key=key + '_ae_f',
                                      help='현장 사정으로 더 힘들었거나(+) 덜 힘들었으면(-) 점수를 더하거나 뺍니다.')
            reason = st.text_input('사유', key=key + '_ae_r', placeholder='예: 13시 원종 조퇴, 광희 대신 G1')
            if st.form_submit_button('적용 (저장 전)'):
                new = deepcopy(s)
                if work != '그대로':
                    new.grid[pid][t] = work
                if fatigue or reason.strip():
                    new.annotations.append({'pid': pid, 't': t, 'fatigue': int(fatigue), 'reason': reason.strip()})
                slot(new)
        for i, a in enumerate(s.annotations):              # 기록된 피로도·사유 (지우기 가능)
            c1, c2 = st.columns([5, 1])
            c1.caption(f"📝 {8 + a['t']:02d}시 {label(a['pid'])} {int(a.get('fatigue', 0)):+d}점 {a.get('reason', '')}")
            if c2.button('지우기', key=f'{key}_ae_del_{i}'):
                new = deepcopy(s)
                new.annotations.pop(i)
                slot(new)
    if dirty:
        c1, c2 = st.columns(2)
        if c1.button('💾 실제 근무 저장', key=key + '_actual_save', type='primary', width='stretch',
                     help='지금 화면을 이 날의 최종 실제 근무로 저장합니다 (이전 저장본은 휴지통 보관).'):
            save_actual(STORE, s, len(changed))
            st.session_state['wd_schedule'] = None            # 다시 그릴 때 새 저장본을 바로 표시
            st.session_state['flash_wd'] = f'{s.day} 실제 근무를 저장했습니다 (바뀐 칸 {len(changed)}개).'
            st.rerun()
        if c2.button('↩ 수정 취소 (저장본으로)', key=key + '_actual_revert', width='stretch'):
            st.session_state['wd_schedule'] = None
            st.rerun()
        st.caption(f"저장하지 않은 수정이 있습니다 · 바뀐 칸 {len(changed)}개 · 주석 {len(s.annotations)}개")


def _delete_saved(s, key):
    """저장된 주말 주간 근무표 삭제 (2026-10-18 사용자 요청, 야간 저장본과 같음): 휴지통으로 옮기고 사이드바
    '🗑 휴지통'에서 언제든 복구. 한 번 더 묻는다."""
    from datetime import date as _date
    from night_shift import history_store
    ask = f'{key}_ask_delete'
    if st.session_state.get(ask):
        st.warning(f'{s.day} 주말 주간 근무표를 삭제할까요? 휴지통으로 옮겨지며 언제든 복구할 수 있습니다.')
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button('삭제', key=f'{key}_delete_yes', type='primary'):
            history_store.delete_to_trash(STORE, _date.fromisoformat(str(s.day)[:10]))
            st.session_state[ask] = False
            for k in ('wd_schedule', 'wd_editing_saved', 'wd_saved_grid', 'wd_saved_ann', 'wd_field'):
                st.session_state.pop(k, None)
            st.session_state['flash_wd'] = f'{s.day} 주말 주간 근무표를 휴지통으로 옮겼습니다.'
            st.rerun()
        if c2.button('취소', key=f'{key}_delete_no'):
            st.session_state[ask] = False
            st.rerun()
    elif st.button('🗑 이 날짜 근무표 삭제', key=f'{key}_delete'):
        st.session_state[ask] = True
        st.rerun()


def _apply_swap(s, event, slot, mobile_key, actual=False):
    """같은 시간 두 번호 교환. LOCK 칸은 바꾸지 않고, 꼭 지킬 규칙을 어기면 거절.
    actual: 저장된 실제 근무 수정 — 현장에서 실제로 그렇게 섰으면 그대로 기록 (규칙 검사로 막지 않음, 야간 저장본과 같음)."""
    a, t = event['a']; b, u = event['b']
    if not (a in s.grid and b in s.grid and t == u and 0 <= t < 10):
        st.session_state['wd_msg'] = '같은 시간의 두 근무자를 교환하세요.'; return
    if not actual and s.locked_through is not None and t <= s.locked_through:
        st.session_state['wd_msg'] = 'LOCK한 시간은 바꿀 수 없습니다.'; return
    if not actual and OFF in (s.grid[a][t], s.grid[b][t]):
        st.session_state['wd_msg'] = '반차·이탈로 근무불가인 칸은 바꿀 수 없습니다.'; return
    new = deepcopy(s)
    new.grid[a][t], new.grid[b][u] = new.grid[b][u], new.grid[a][t]
    errors = [] if actual else validate(new)
    if errors:
        st.session_state['wd_msg'] = '교환 불가: ' + '; '.join(errors[:4]); return
    slot(new)


def _run_emergency(s, lock, pid, kind, results, view_key):
    """긴급 오후반차·이탈 재편성 (PC 표 클릭·폰 입력칸 공통). lock 칸까지 기존 배정 그대로."""
    try:
        with st.spinner('LOCK 구간은 그대로 두고 남은 시간을 재편성 중입니다…'):
            new, status = reoptimize(s, lock, pid, kind, seconds=30, history=history_debt(STORE, s.day)[0], patrol_events=load_events(store_dir(), s.day, 'day'))
    except ValueError as exc:
        st.session_state['wd_msg'] = str(exc); st.rerun()
    if new is None:
        st.session_state['wd_msg'] = (
            '빠지고 나면 일반근무자가 3명인 시간이 생깁니다. 주말 주간 룰북 지원 범위 밖이라 수기로 편성하세요.'
            if status == 'UNSUPPORTED' else
            '해가 없습니다. 남은 인원과 LOCK을 유지하면서 필수규칙과 피로도 격차 2 이내를 함께 만족할 수 없습니다. '
            '규칙을 자동으로 완화하지 않았습니다.' if status == 'INFEASIBLE' else
            f'시간 안에 재편성표를 찾지 못했습니다 ({status}). 불가능 판정은 아닙니다.')
        st.rerun()
    # params: 표 아래 '🔁 근무표 재생성'으로 같은 LOCK·빠진 사람 조건의 다른 재편성안을 만들 때 (2026-10-18)
    results.append({'schedule': new, 'status': status, 'initial': deepcopy(new), 'params': (s, lock, pid, kind)})
    st.session_state[view_key + '_pending'] = len(results) - 1
    st.rerun()


def _regen_emergency(results, index, view_key):
    """긴급 재편성표 재생성: 같은 원래 표·LOCK·빠진 사람·종류로, 지금까지의 재편성안과 다른 표를 새로 추가."""
    params = results[index].get('params')
    if params is None:
        st.session_state['wd_msg'] = '이 재편성표는 조건 기록이 없어 다시 만들 수 없습니다. 원래 표에서 다시 재편성해 주세요.'
        st.rerun()
    base, lock, pid, kind = params
    avoid = [r['schedule'].grid for r in results if r.get('params') and r['params'][1:] == params[1:]]
    with st.spinner('LOCK 구간은 그대로 두고 다른 재편성안을 만드는 중입니다…'):
        new, status = reoptimize(base, lock, pid, kind, seconds=30, exclude=avoid,
                                 history=history_debt(STORE, base.day)[0],
                                 patrol_events=load_events(store_dir(), base.day, 'day'))
    if new is None:
        st.session_state['wd_msg'] = ('같은 조건으로 다른 재편성안이 더 없습니다.' if status == 'INFEASIBLE' else
                                      f'시간 안에 다른 재편성안을 찾지 못했습니다 ({status}). 불가능 판정은 아닙니다.')
        st.rerun()
    results.append({'schedule': new, 'status': status, 'initial': deepcopy(new), 'params': params})
    st.session_state[view_key + '_pending'] = len(results) - 1
    st.rerun()


def _current_candidate():
    """지금 화면에 보이는 생성 후보 (저장본을 보는 중이면 None)."""
    ck, ik = st.session_state.get('wd_cand_keys', (None, None))
    i = st.session_state.get(ik) if ik else None
    cands = st.session_state.get(ck) or []
    return cands[i] if i is not None and i < len(cands) else None


def _badges(items):
    """표 위 상태 표시 (야간 status_badge와 같은 모양): (글자, 'ok'|'warn'|'idle'|'info')."""
    tones = {'ok': ('#DCFCE7', '#166534'), 'warn': ('#FEF3C7', '#92400E'),
             'idle': ('#F1F5F9', '#475569'), 'info': ('#DBEAFE', '#1E40AF')}
    st.markdown("<div style='margin:0 0 6px'>" + ''.join(
        f"<span style='display:inline-block;background:{tones[t][0]};color:{tones[t][1]};border-radius:999px;"
        f"padding:3px 12px;margin:0 6px 4px 0;font-weight:700;font-size:.85rem'>{escape(text)}</span>"
        for text, t in items) + "</div>", unsafe_allow_html=True)


def person_hours(s, pid, view):
    """직원 상세분석 (2026-10-18): 시간별 업무·구분·피로도·누적. 피로도 = 입식 2·좌식 1·순찰 구역 점수 + 기록 가감."""
    rows, total = [], 0
    for t, v in enumerate(s.grid[pid]):
        if v == OFF:
            kind, point = '근무불가', 0
        elif v in ('휴게', STANDBY) or (view == '유도리' and v == 'G2'):
            kind, point = {'G2': '휴게성', STANDBY: '보안실 대기'}.get(v, '휴게'), 0
        elif v == '순찰':
            kind, point = f'순찰 {PATROL[t][0]}', PATROL[t][1]
        elif v == 'I1':
            kind, point = '좌식', 1
        else:
            kind, point = '입식', 2
        notes = [a for a in s.annotations if a.get('pid') == pid and a.get('t') == t]
        point += sum(int(a.get('fatigue', 0)) for a in notes)
        total += point
        rows.append({'시간': f'{8 + t:02d}시', '업무': v, '구분': kind, '피로도': point, '누적 피로도': total,
                     '기록': ' / '.join(a.get('reason', '') for a in notes if a.get('reason'))})
    return rows


def _person_detail(s, key, view):
    """직원 한 명의 시간대별 업무·피로도 (야간 '직원 상세분석'과 같은 뜻, PC·폰 공통)."""
    label = lambda p: person_label(s, p) + (f' ({leave_text(s, p)})' if leave_text(s, p) else '')
    pid = st.selectbox('직원', list(s.grid), format_func=label, key=key + '_detail_person')
    row = next(r for p, r in zip(s.grid, stats(s, view)) if p == pid)
    st.caption(f"{view} 기준 · 실근무 {row['실근무']}시간 · 실휴게 {row['실휴게']}시간 · 피로도 {row['피로도']}점 "
               f"(입식 {row['입식']} · 좌식 {row['좌식']} · 순찰 {row['순찰 피로도']} · 기타 {row['기타 피로도']})")
    st.dataframe(pd.DataFrame(person_hours(s, pid, view)), hide_index=True, use_container_width=True)


def _mobile_emergency(s, key, results, view_key):
    """폰: '몇 시까지 LOCK → 누가 → 오후반차/이탈' 입력칸 (PC 표 클릭과 같은 재편성 엔진)."""
    floor = s.locked_through + 1 if s.locked_through is not None else 0
    hours = list(range(floor, 9))
    if not hours:
        st.caption('LOCK 뒤에 남은 시간이 없습니다.'); return
    lock = st.selectbox('① 이미 진행된(진행 중) 마지막 시간 — 여기까지 LOCK', hours,
                        format_func=lambda t: f'{8 + t:02d}시까지 그대로', key=key + '_mlock')
    start = lock + 1
    people = emergency_candidates(s, start)
    if not people:
        st.caption('빠질 수 있는 일반근무자가 없습니다.'); return
    pid = st.selectbox('② 빠지는 사람', people, format_func=lambda p: person_label(s, p), key=key + '_mpid')
    kinds = (['half'] if start <= HALF_DAY_LEAVE and pid not in s.half_days else []) + ['leave']
    labels = {'half': '오후반차 (13시 퇴근)', 'leave': f'긴급 이탈 ({8 + start}시부터)'}
    kind = st.radio('③ 종류', kinds, format_func=labels.get, horizontal=True, key=key + '_mkind')
    if st.button('재편성', type='primary', width='stretch', key=key + '_mrun'):
        _run_emergency(s, lock, pid, kind, results, view_key)


def _show(s, key, status, results, view_key, mobile, index):
    """근무표 한 장: n빵 판정·표(끌어 교환·긴급 LOCK)·비교표·검증·저장."""
    from history_ui import emergency_toggle, emergency_box
    if st.session_state.get('wd_msg'):
        st.error(st.session_state.pop('wd_msg'))
    field = st.session_state.get('wd_field')
    _field_download(s, _saved_review(s.day) if field and field[0] == id(s) else None, key)
    if s.leavers:
        st.info(f"긴급 재편성표 · {8 + s.locked_through:02d}시까지 기존 배정 LOCK · "
                f"{8 + s.locked_through + 1:02d}시부터 다시 편성  \n빠진 사람: "
                + ', '.join(f'{person_label(s, p)} {leave_text(s, p)}' + (
                    ' · 나온 5시간 중 휴게 ' + ' / '.join(f'{v} {half_rest_hours(s, p, v)}시간' for v in views_of(s))
                    + ' (목표 1시간, 다른 근무자 밸런스 다음)' if s.leavers[p]['kind'] == 'half' else '')
                    for p in s.leavers))
    if s.half_days:
        st.info('반차: ' + ', '.join(
            f"{person_label(s, p)} {v} ({'08~12시 근무' if v == '오후반차' else '13~17시 근무'}) · 휴게 "
            + ' / '.join(f'{m} {half_rest_hours(s, p, m)}시간' for m in views_of(s)) + ' (목표 1시간)'
            for p, v in s.half_days.items()))
    st.markdown(nbbang_text(s, status))

    cand = _current_candidate() if index is None else None

    def replace(new):
        if index is None:
            st.session_state['wd_schedule'] = new; st.session_state['wd_status'] = None
            if cand is not None:                      # 교환 내용은 후보마다 보관 (후보를 바꿔 봐도 그대로)
                cand['schedule'] = new
        else:
            results[index] = {**results[index], 'schedule': new, 'status': None}
        st.rerun()
    lock_key = key + '_lock'
    lock = st.session_state.get(lock_key)
    floor = s.locked_through + 1 if s.locked_through is not None else 0
    if mobile:
        with emergency_box(key + '_em'):
            _mobile_emergency(s, key, results, view_key)
        opened = False
    else:
        opened = emergency_toggle(key + '_em', force=lock is not None, lock_key=lock_key)
    clickable = list(range(floor, 9)) if opened else []          # 17시는 LOCK 뒤에 남는 시간이 없어 제외
    if lock is not None and lock not in clickable:
        lock = st.session_state[lock_key] = None
    menus, eligible = {}, set()
    if lock is not None:
        start = lock + 1
        for p in emergency_candidates(s, start):
            menus[p] = ([{'label': '오후반차 (13시 퇴근)', 'value': 'half'}]
                        if start <= HALF_DAY_LEAVE and p not in s.half_days else []) + \
                       [{'label': f'긴급 이탈 ({8 + start:02d}시부터)', 'value': 'leave'}]
            eligible.add(p)
    # 저장된 실제 근무 수정 중 (2026-10-13 사용자 요청, 야간 저장본과 같음): 끌어 교환·칸 직접 수정·피로도·사유
    editing = (index is None and st.session_state.get('wd_editing_saved') == str(s.day)
               and (STORE/f'{s.day}.json').exists())
    base_grid = st.session_state.get('wd_saved_grid') or {}
    changed = frozenset((p, t) for p, row in s.grid.items() for t in range(10)
                        if editing and row[t] != (base_grid.get(p) or [None] * 10)[t])
    dirty = editing and (bool(changed) or s.annotations != st.session_state.get('wd_saved_ann', []))
    # FM·유도리 보기 버튼 (2026-10-16 사용자 요청, 야간과 같음): FM 표·G2 운영일 때만. 처음은 FM.
    vkey = key + '_fmview'
    toggle = s.mode == 'FM' and g2_open(s)
    shown = st.session_state.get(vkey, 'FM') if toggle else None
    html = sheet_html(s, lock, clickable, eligible, compact=mobile, changed=changed, view=shown)
    if clickable:
        html = _steps_html(lock) + html
    field = st.session_state.get('wd_field')
    is_field = bool(field and field[0] == id(s))
    # 표 처음 상태 (↩ 초기 생성표로 · ✏️ 수정됨 표시): 생성 후보·긴급 재편성표마다
    initial = cand['initial'] if cand is not None else results[index].get('initial') if index is not None else None
    modified = initial is not None and (initial.grid != s.grid or initial.annotations != s.annotations)
    # 상태 표시 (2026-10-18 사용자 요청, 야간 상태 배지와 같음)
    exists = (STORE/f'{s.day}.json').exists()
    chips = ([('📥 현장 업로드 표', 'idle')] if is_field else
             [('💾 저장본', 'ok')] + ([('✏️ 수정됨 · 저장 안 됨', 'warn')] if dirty else []) if editing else
             [('🕓 미저장 (생성만 됨)', 'warn')] + ([('✏️ 교환 수정됨', 'warn')] if modified else []))
    if index is not None:
        chips.append((f'🔒 긴급 재편성 {index + 1}', 'info'))
    elif cand is not None and len(st.session_state[st.session_state['wd_cand_keys'][0]]) > 1:
        chips.append((f"후보 {st.session_state[st.session_state['wd_cand_keys'][1]] + 1}", 'info'))
    _badges(chips)
    from datetime import date as _date
    if editing and _flex_relevant(s) and str(s.day) < _date.today().isoformat():
        # 지난 FM 표: 실제 유도리 운영 여부 (맨 위 배너와 같은 값, 여기서 언제든 바꿈 — 기본 유도리)
        now_flex = flex_actual(s.day)
        picked = st.radio('이날 실제 운영 (막타임 순번 계산에 사용)', ('유도리', 'FM'), index=0 if now_flex else 1,
                          horizontal=True, key=f'{key}_flex_actual_{now_flex}')
        if (picked == '유도리') != now_flex:
            set_flex_actual(s.day, picked); st.rerun()
    if mobile:
        event = _DAY_GRID(data={'html': html, 'menus': menus, 'edit': True, 'name_pin': True}, key=key + '_grid', default=None)
    else:                                             # PC: 표 오른쪽 빈 공간에 특이사항·비고 (2026-10-13 사용자 요청)
        left, right = st.columns([2, 1])
        with left:
            event = _DAY_GRID(data={'html': html, 'menus': menus, 'edit': True, 'name_pin': True}, key=key + '_grid', default=None)
        with right:
            _notes(s, is_field, shown, tables=False)
    if isinstance(event, dict) and event.get('nonce') and event['nonce'] != st.session_state.get('wd_nonce'):
        st.session_state['wd_nonce'] = event['nonce']
        kind = event.get('kind')
        if kind == 'view':
            if toggle:
                st.session_state[vkey] = '유도리' if event.get('mode') == '유도리' else 'FM'
            st.rerun()
        elif kind == 'swap':
            _apply_swap(s, event, replace, key, actual=editing)
            st.rerun()
        elif kind in ('move', 'rowswap'):
            st.session_state['wd_msg'] = '같은 시간의 번호끼리 교환할 수 있습니다.'; st.rerun()
        elif kind == 'hour' and opened:
            t = int(event['t'])
            st.session_state[lock_key] = None if lock == t else t
            st.rerun()
        elif kind == 'person' and lock is not None and event.get('pid') in eligible:
            st.session_state[lock_key] = None
            _run_emergency(s, lock, event['pid'], event.get('choice') or 'leave', results, view_key)
    if not editing:                                   # 표 바로 아래 한 줄: 저장 · 초기 생성표로 · 재생성 (야간과 같음)
        from mobile_ui import action_columns
        blocked = validate(s)
        with action_columns(key + '_act', spec=3) as (c1, c2, c3):
            with c1:
                if s.leavers:     # 긴급 재편성표: 저장본이 있으면 휴지통에 백업 후 교체
                    if st.button('💾 이 재편성표 저장', key=key + '_save', type='primary', width='stretch',
                                 disabled=bool(blocked),
                                 help='기존 저장본은 휴지통에 보관하고 교체합니다.' if exists else None):
                        path = STORE/f'{s.day}.json'
                        if exists:
                            trash = STORE/'.trash'; trash.mkdir(parents=True, exist_ok=True)
                            path.replace(trash/f'{s.day}_{datetime.now():%Y%m%d_%H%M%S}.json')
                        save(STORE, s); st.session_state['flash_wd'] = '공휴일 주간 기록에 재편성표를 저장했습니다.'
                        st.session_state['wd_schedule'] = None
                        st.rerun()
                elif st.button('💾 저장', key=key + '_save', type='primary', width='stretch',
                               disabled=bool(blocked) or exists,
                               help='이미 저장된 날짜는 덮어쓰지 않습니다(긴급 재편성표는 백업 후 교체).' if exists
                               else '이 표를 공휴일 주간 기록으로 저장합니다.'):
                    save(STORE, s); st.session_state['flash_wd'] = '공휴일 주간 기록에 저장했습니다.'
                    st.session_state['wd_schedule'] = None
                    st.rerun()
            with c2:
                if st.button('↩ 초기 생성표로', key=key + '_initial', width='stretch', disabled=not modified,
                             help='처음 생성했을 때의 배정·주석으로 되돌립니다(저장하지 않음).'):
                    replace(deepcopy(initial))
            with c3:
                if st.button('🔁 근무표 재생성', key=key + '_regen', width='stretch',
                             help='LOCK·빠진 사람은 그대로 두고 다른 재편성안을 만듭니다.' if index is not None
                             else '같은 조건으로 이전 후보들과 다른 근무표를 새 후보로 만듭니다.'):
                    if index is None:
                        st.session_state['wd_regen_req'] = str(s.day)
                        st.rerun()
                    _regen_emergency(results, index, view_key)
        if exists and not s.leavers:
            st.caption('이 날짜에 저장된 표가 있어 덮어쓰지 않습니다(긴급 재편성표는 백업 후 교체 가능).')
    if editing:
        _actual_editor(s, replace, key, changed, dirty)
        _delete_saved(s, key)
    tab_all, tab_person = st.tabs(('전체 비교', '직원 상세분석'))
    with tab_all:
        for view in ((shown,) if shown else views_of(s)):     # 보기 버튼이 있으면 고른 기준 한 장만
            st.markdown(f'**{view} 전체 비교표**' if g2_open(s) else '**전체 비교표** (G2 미운영 · FM·유도리 같음)')
            frame = pd.DataFrame(stats(s,view))
            st.dataframe(frame, hide_index=True, use_container_width=True)
            general = frame.iloc[[i for i,p in enumerate(s.grid) if p != 'A' and p not in partial_people(s)]]
            st.caption(f'일반근무자 격차{" (반차·이탈자 제외)" if partial_people(s) else ""}: '
                       f'실근무 {general["실근무"].max()-general["실근무"].min()}시간 / '
                       f'피로도 {general["피로도"].max()-general["피로도"].min()}점')
    with tab_person:
        _person_detail(s, key, shown or ('FM' if s.mode == 'FM' else '유도리'))
    if is_field:                                     # 불러온 현장 실제 근무표 그대로 (바꾸면 새 표라 다시 검사)
        errors = []
        st.caption(f'📥 현장 실제 근무표 ({field[1]}) — 생성 규칙 검사 대상 아님')
    elif editing and (errors := validate(s)):        # 실제 근무 기록: 생성 규칙과 다른 점은 참고로만 (저장 가능)
        st.warning('생성 규칙과 다른 점(실제 근무 기록이라 그대로 저장할 수 있습니다): ' + '; '.join(errors))
        errors = []
    elif errors := validate(s): st.error('검증 오류: '+'; '.join(errors))
    else: st.success('선택한 편성 조건 검증 통과'+(' · G2 미운영' if not g2_open(s) else
                                                  ' · FM·유도리 양쪽 만족' if s.mode == 'FM' else ' · 유도리 기준'))
    soft = advisories(s)
    if soft:        # 긴급 재편성: 가능하면 지킬 규칙으로 낮춘 연속 실근무 상한·격차 1
        st.warning(f'긴급 재편성이라 가능하면 지킬 규칙 {len(soft)}건을 못 지켰습니다(남은 인원으로 불가피):  \n'
                   + '  \n'.join('· ' + line for line in soft))
    repeats = repeats_of(s)
    st.caption('같은 포스트 2연속(강한 비권장): ' + (', '.join(repeats) if repeats else '없음'))
    if mobile:                                        # 폰: 표 아래 (PC는 표 오른쪽)
        _notes(s, is_field, shown)
    else:                                             # PC: 순찰·막타임 표는 전체 폭으로 (비고 칸은 좁음)
        _cycle_tables(s, shown)
    if index is not None and st.button('🗑 이 재편성 버리기', key=key+'_drop'):
        results.pop(index)
        st.session_state[view_key + '_pending'] = 'base'
        st.rerun()
    if st.session_state.get('flash_wd'):
        st.success(st.session_state.pop('flash_wd'))
    rows = [{'시간':f'{8+t:02}~{9+t:02}', **{v:' · '.join(display_numbers(s)[p] for p,row in s.grid.items() if row[t] == v) for v in LABELS + (STANDBY, OFF)}} for t in range(10)]
    st.download_button('근무표 CSV 다운로드', pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),
                       file_name=f'{s.day}_공휴일주간.csv', mime='text/csv', key=key+'_csv')
