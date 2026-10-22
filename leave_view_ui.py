"""연차일정 탭 (2026-10-06 사용자 요청): 앱에 올린 연차일정을 한 달 달력으로 항상 한눈에. PC 달력·폰 날짜 목록."""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

import mobile_ui
from history_ui import store_dir
from night_shift import daily_report as dr
from night_shift.calendar_info import holiday_name, is_off_day
from night_shift.leave_schedule import (load, save_text, replace_uploaded_text, load_manual, save_manual, delete_manual,
                                       hide_original, HIDE_KIND)

KINDS = ["연차", "오전반차", "오후반차", "전반야 반차", "후반야 반차", "교육", "훈련", "야간지원", "주간지원", "휴무", "병가", "출근", "퇴사", "기타"]


def manual_box(store) -> None:
    with st.expander("인원별 일정 직접 등록·수정", expanded=False):
        st.caption("직접 등록한 일정은 PC·폰에 함께 적용되며 같은 사람·날짜의 원본 일정보다 우선합니다. 삭제하면 원본 일정이 다시 적용됩니다. 새 연차일정 파일을 저장하면 직접 등록 일정은 초기화됩니다.")
        st.caption("이전 출근 정정 기록도 일정에 반영되며, 새로 직접 등록한 일정이 우선합니다.")
        if message := st.session_state.pop("manual_leave_message", None):
            st.success(message)
        items = load_manual(store)
        choices = {i["id"]: i for i in items}
        selected = st.selectbox("등록 또는 수정", ["새 일정"] + list(choices),
                                format_func=lambda x: x if x == "새 일정" else f"{choices[x]['start']} ~ {choices[x]['end']} · {choices[x]['name']} · {choices[x]['kind']}", key="manual_leave_pick")
        item = choices.get(selected, {})
        roster = dr.load_roster(store)
        names = list(dict.fromkeys(r["이름"] for r in roster))
        if item.get("name") and item["name"] not in names:
            names.append(item["name"])
        if not names:
            st.info("근태관리일보에서 조별 근무자 명단을 먼저 등록하세요.")
            return
        kinds = list(KINDS)
        kind = item.get("kind", "연차")
        if kind not in kinds:
            kinds.append(kind)
        # 종류를 폼 밖에서 먼저 고른다: 퇴사를 고르면 바로 '마지막 근무일' 한 칸으로 바뀜 (2026-10-12 사용자 지적)
        kind = st.selectbox("일정 종류", kinds, index=kinds.index(kind), key=f"manual_kind_{selected}")
        retire = kind == "퇴사"
        if retire:
            done = sorted(((r["이름"], str(r["종료"])[:10]) for r in roster if r.get("종료")), key=lambda x: x[1])
            if done:
                st.caption("현재 퇴사 처리: " + " · ".join(
                    f"{n} {e[5:].replace('-', '/')} 마지막 근무 ({'퇴사 완료' if date.fromisoformat(e) < date.today() else '예정'})"
                    for n, e in done) + " — 같은 사람을 다시 저장하면 마지막 근무일이 바뀝니다.")
        with st.form(f"manual_leave_form_{selected}_{retire}"):
            name = st.selectbox("인원", names, index=names.index(item.get("name", names[0])))
            if retire:
                start = end = st.date_input("마지막 근무일", value=date.fromisoformat(item["start"]) if item else date.today(),
                                            format="YYYY-MM-DD")
                presence = "출근"
                st.caption("이날까지 출근(일보 비고 '퇴사')하고, 다음 날부터 일보·근무 편성·명령서 명단에서 빠집니다. "
                           "7일 전부터 모든 탭 위에 퇴사 예정 안내가 나옵니다.")
            else:
                start = st.date_input("시작일", value=date.fromisoformat(item["start"]) if item else date.today(), format="YYYY-MM-DD")
                end = st.date_input("종료일", value=date.fromisoformat(item["end"]) if item else date.today(), format="YYYY-MM-DD")
                presence = st.selectbox("출근 여부", ["자동", "출근", "미출근"], index=["자동", "출근", "미출근"].index(item.get("presence", "자동")))
                st.caption("자동: 연차·휴무·훈련은 미출근, 교육은 일보 출근 비고/편성 제외, 반차는 해당 시간 제외, 야간지원은 주간 제외(주간지원은 야간 제외). 기타는 출근 여부를 직접 선택하세요.")
            note = st.text_input("비고", value=item.get("note", ""))
            submitted = st.form_submit_button("퇴사 저장" if retire else "일정 저장")
        if submitted:
            if kind == "기타" and presence == "자동":
                st.error("기타 일정은 출근 또는 미출근을 선택하세요.")
            else:
                group = next((r["소속"] for r in roster if r["이름"] == name), "")
                try:
                    save_manual(store, name, dr.TEAM_LETTER.get(group, ""), start, end, kind, note, presence, item.get("id"))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    if kind == "퇴사":
                        dr.set_last_day(store, name, start)
                    st.session_state["manual_leave_message"] = (f"{name} 퇴사를 저장했습니다. {start:%m/%d}이 마지막 근무일이고 다음 날부터 명단에서 빠집니다."
                                                                if kind == "퇴사" else "일정을 저장했습니다. 달력에 [직접 등록]으로 표시됩니다.")
                    st.rerun()
        if item and st.button("이 직접 등록 일정 삭제", key=f"manual_delete_{selected}"):
            if item.get("kind") == "퇴사":                 # 퇴사 취소 = 명단 종료일도 지움
                dr.set_last_day(store, item["name"], None)
            delete_manual(store, selected)
            st.session_state["manual_leave_message"] = "직접 등록 일정을 삭제했습니다. 원본 일정이 있으면 다시 적용됩니다."
            st.rerun()

# 종류별 색 (배경, 글자)
TONES = {"사고": ("#FEE2E2", "#991B1B"), "반차": ("#FFEDD5", "#9A3412"), "지원": ("#DBEAFE", "#1E40AF"),
         "교육": ("#EDE9FE", "#5B21B6"), "인사": ("#E5E7EB", "#374151"), "기타": ("#FFFFFF", "#111827")}
SHORT = {"주간고정": "고정", "A조": "A", "B조": "B", "C조": "C", "안내": "안내", "주차": "주차"}


def wedding_box(store) -> None:
    """💒 웨딩 있는 날 직접 입력 (2026-10-13 사용자 요청). 표기만, 근무 규칙과 무관. PC·폰 공통."""
    from night_shift import wedding
    days = wedding.load(store)
    upcoming = [d for d in days if d >= date.today()]
    with st.expander(f"💒 웨딩 일정 ({len(upcoming)}건 예정)", expanded=False):
        st.caption("결혼식이 있는 날을 넣으면 연차일정·근무표 달력과 그날 주말 주간 근무표에 💒로 표시됩니다. 근무 편성 규칙은 바뀌지 않습니다.")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        day = c1.date_input("날짜", key="wedding_day", format="YYYY-MM-DD")
        if c2.button("💒 웨딩 있음 추가", key="wedding_add", width="stretch"):
            added = wedding.add(store, day)
            st.session_state["wedding_msg"] = (f"{day:%m/%d} 웨딩을 추가했습니다." if added else f"{day:%m/%d}은 이미 웨딩으로 등록돼 있습니다.")
            st.rerun()
        if day and not is_off_day(day):
            st.caption(f"참고: {day:%m/%d}은 평일입니다(그래도 등록할 수 있습니다).")
        if msg := st.session_state.pop("wedding_msg", None):
            st.success(msg)
        shown = upcoming or days[-5:]
        if not shown:
            st.caption("등록된 웨딩이 없습니다.")
        for d in shown:
            a, b = st.columns([3, 1], vertical_alignment="center")
            a.markdown(f"💒 **{d:%Y-%m-%d}** ({'일월화수목금토'[(d.weekday() + 1) % 7]})"
                       + (f" · {holiday_name(d)}" if holiday_name(d) else ""))
            if b.button("삭제", key=f"wedding_del_{d}", width="stretch"):
                wedding.remove(store, d)
                st.session_state["wedding_msg"] = f"{d:%m/%d} 웨딩을 지웠습니다."
                st.rerun()
        if upcoming and len(days) > len(upcoming):
            st.caption(f"지난 웨딩 {len(days) - len(upcoming)}건은 달력에서 확인할 수 있습니다.")


def tone(kind: str) -> str:
    k = kind.replace(" ", "")
    if "반차" in k or "반야" in k:
        return "반차"
    if "지원" in k or "대근" in k:
        return "지원"
    if "교육" in k or "검진" in k:
        return "교육"
    if any(w in k for w in ("입사", "퇴사", "편입", "전입", "전출", "명단")) and "연차" not in k:
        return "인사"
    what = [w for w, _ in dr.classify(kind)]
    return "사고" if "absent" in what else "기타"


def upload_box(store, key: str) -> None:
    """연차일정 텍스트 올리기 (근태관리 일보·연차일정 탭 공통). 기존 내용 교체."""
    if message := st.session_state.pop("leave_upload_message", None):
        st.success(message)
    with st.expander("연차일정 · CP 근무표 올리기", expanded=False):
        st.caption("카카오톡 '연차일정(2026).txt'를 올리면 근무표·일보·연차일정 탭이 모두 이 내용으로 바뀝니다. 기존 직접 등록·출근 정정은 백업 후 초기화합니다.")
        st.caption('CP 월간 근무표 엑셀·이미지도 여기서 올리고 저장하면 해당 근무일에 자동 적용됩니다.')
        upload = st.file_uploader("연차일정 텍스트 또는 CP 근무표 엑셀·이미지", type=["txt","xlsx","png","jpg","jpeg","webp"], key=f"{key}_file", label_visibility="collapsed")
        if upload is not None and upload.name.lower().endswith(('.png','.jpg','.jpeg','.webp')):
            from cp_image_ui import render
            render(upload.getvalue(),upload.name)
            return
        if upload is not None and upload.name.lower().endswith('.xlsx'):
            from import_ui import render_cp
            render_cp(upload.getvalue(),upload.name,'leave_upload_message')
            return
        if upload is not None and st.button("이 연차일정으로 저장", key=f"{key}_save"):
            raw = upload.getvalue()
            for enc in ("utf-8-sig", "cp949"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                st.error("글자 인코딩을 읽지 못했습니다.")
                return
            try:
                replace_uploaded_text(store, text)
            except ValueError as exc:
                st.error(str(exc)); return
            st.session_state["leave_upload_message"]="연차일정을 업로드 내용으로 교체했습니다. 기존 직접 등록·출근 정정은 백업 후 초기화했습니다."
            st.rerun()


_LEAVE_CALENDAR = None


def leave_calendar(store, html: str, chips: dict, key: str) -> None:
    """누를 수 있는 연차일정 달력(2026-10-23 사용자 요청): 칩 → 수정·삭제 창, ＋ → 그 날짜 추가 창. PC·폰 공통."""
    global _LEAVE_CALENDAR
    if _LEAVE_CALENDAR is None:
        import streamlit.components.v1 as components
        from pathlib import Path
        _LEAVE_CALENDAR = components.declare_component(
            "leave_calendar", path=str(Path(__file__).resolve().parent / "night_shift" / "leave_calendar"))
    event = _LEAVE_CALENDAR(data={"html": html}, key=f"leave_calendar_{key}", default=None)
    if isinstance(event, dict) and event.get("nonce") and event["nonce"] != st.session_state.get("leave_calendar_nonce"):
        st.session_state["leave_calendar_nonce"] = event["nonce"]
        open_leave_dialog(store, event, chips)


def open_leave_dialog(store, event: dict, chips: dict) -> None:
    entry = chips.get((event.get("key"), event.get("date"))) if event.get("kind") == "chip" else None
    from uuid import uuid4                        # 창마다 입력칸을 새로(직전 창 값이 남지 않게)
    st.session_state["leave_dialog"] = {"event": event, "entry": entry, "mode": "menu" if entry else "add",
                                        "token": uuid4().hex[:8]}
    leave_dialog(store)


@st.dialog("연차일정")
def leave_dialog(store) -> None:
    state = st.session_state.get("leave_dialog") or {}
    event, entry, mode = state.get("event", {}), state.get("entry"), state.get("mode")
    token = state.get("token", "")
    day = date.fromisoformat(event.get("date") or date.today().isoformat())
    roster = dr.load_roster(store)
    if mode == "menu" and entry:
        label = f"{entry['name']} {entry['kind']}" + (f" · {entry['note']}" if entry.get("note") else "")
        if entry.get("manual"):
            span = entry["start"] if entry["start"] == entry["end"] else f"{entry['start']} ~ {entry['end']}"
            st.markdown(f"**{label}** [직접 등록]  \n{span}")
        else:
            st.markdown(f"**{label}** (연차일정 파일 원본)  \n{day:%Y-%m-%d}")
        c1, c2 = st.columns(2)
        if c1.button("✏️ 수정", key=f"leave_dlg_edit_{token}", width="stretch"):
            state["mode"] = "edit"
            st.rerun(scope="fragment")
        if c2.button("🗑️ 삭제", key=f"leave_dlg_delete_{token}", width="stretch"):
            if entry.get("manual"):
                if entry.get("kind") == "퇴사":            # 퇴사 취소 = 명단 종료일도 지움
                    dr.set_last_day(store, entry["name"], None)
                delete_manual(store, entry["id"])
                message = (f"{entry['name']} {entry['kind']} 직접 등록을 지웠습니다"
                           + (f"({entry['start']} ~ {entry['end']} 전체)." if entry["start"] != entry["end"] else ".")
                           + " 원본 일정이 있으면 다시 보입니다.")
            else:
                group = next((r["소속"] for r in roster if r["이름"] == entry["name"]), "")
                try:
                    hide_original(store, entry["name"], dr.TEAM_LETTER.get(group, entry.get("team", "")), day)
                except ValueError as exc:
                    st.error(str(exc))
                    return
                message = f"{day:%m/%d} {entry['name']} {entry['kind']} 일정을 지웠습니다(원본 파일은 그대로, 이날만 숨김)."
            st.session_state["leave_dialog"] = None
            st.session_state["manual_leave_message"] = message
            st.rerun()
        if entry.get("manual") and entry["start"] != entry["end"]:
            st.caption("기간으로 등록한 직접 일정은 수정·삭제가 기간 전체에 적용됩니다.")
        return
    item = entry if entry and entry.get("manual") else {}
    names = list(dict.fromkeys(r["이름"] for r in roster))
    default_name = (entry or {}).get("name")
    if default_name and default_name not in names:
        names.append(default_name)
    if not names:
        st.info("근태관리일보에서 조별 근무자 명단을 먼저 등록하세요.")
        return
    kinds = list(KINDS)
    default_kind = (entry or {}).get("kind", "연차")
    if default_kind not in kinds:
        kinds.append(default_kind)
    st.markdown("**일정 수정**" if entry else f"**{day:%m/%d} 일정 추가**")
    name = st.selectbox("인원", names, index=names.index(default_name) if default_name else 0, key=f"leave_dlg_name_{token}")
    kind = st.selectbox("일정 종류", kinds, index=kinds.index(default_kind), key=f"leave_dlg_kind_{token}")
    retire = kind == "퇴사"
    first = date.fromisoformat(item["start"]) if item else day
    if retire:
        start = end = st.date_input("마지막 근무일", value=first, format="YYYY-MM-DD", key=f"leave_dlg_last_{token}")
        presence = "출근"
    else:
        start = st.date_input("시작일", value=first, format="YYYY-MM-DD", key=f"leave_dlg_start_{token}")
        end = st.date_input("종료일", value=date.fromisoformat(item["end"]) if item else day, format="YYYY-MM-DD",
                            key=f"leave_dlg_end_{token}")
        options = ["자동", "출근", "미출근"]
        presence = st.selectbox("출근 여부", options, index=options.index(item.get("presence", "자동")) if item else 0,
                                key=f"leave_dlg_presence_{token}")
    note = st.text_input("비고", value=item.get("note", "") if item else (entry or {}).get("note", ""), key=f"leave_dlg_note_{token}")
    if entry and not item:
        st.caption(f"원본 일정은 파일을 고치지 않고 직접 등록으로 덮어씁니다(기간을 바꾸면 그 기간 전체).")
    if st.button("저장", type="primary", key=f"leave_dlg_save_{token}", width="stretch"):
        if kind == "기타" and presence == "자동":
            st.error("기타 일정은 출근 또는 미출근을 선택하세요.")
            return
        group = next((r["소속"] for r in roster if r["이름"] == name), "")
        try:
            save_manual(store, name, dr.TEAM_LETTER.get(group, ""), start, end, kind, note, presence, item.get("id"))
        except ValueError as exc:
            st.error(str(exc))
            return
        if retire:
            dr.set_last_day(store, name, start)
        st.session_state["leave_dialog"] = None
        st.session_state["manual_leave_message"] = f"{name} {kind} 일정을 저장했습니다. 달력에 [직접 등록]으로 표시됩니다."
        st.rerun()


def page() -> None:
    st.title("연차일정")
    store = store_dir()
    import date_check_ui                         # 날짜를 고르면 일보·근무표·명령서 대조 결과 (2026-10-07)
    st.session_state.setdefault("leave_check_day", date.today())
    check_day = st.date_input("대조할 날짜", key="leave_check_day", format="YYYY-MM-DD")
    date_check_ui.banner(check_day)
    manual_box(store)
    wedding_box(store)
    from night_shift import wedding
    weddings = set(wedding.load(store))
    mobile = mobile_ui.is_mobile()
    today = date.today()
    st.session_state.setdefault("leave_month", (today.year, today.month))
    year, month = st.session_state["leave_month"]
    c1, c2, c3, c4 = st.columns([1, 2, 1, 3])
    if c1.button("◀ 이전 달", key="leave_prev"):
        st.session_state["leave_month"] = (year - 1, 12) if month == 1 else (year, month - 1)
        st.rerun()
    c2.markdown(f"### {year}년 {month}월")
    if c3.button("다음 달 ▶", key="leave_next"):
        st.session_state["leave_month"] = (year + 1, 1) if month == 12 else (year, month + 1)
        st.rerun()
    with c4:
        upload_box(store, "leave_view_upload")
    entries = load(store, year)
    # 2026-10-18 사용자 요청: 달력(전체 조) 옆에 A조 월간표·연간표 (다른 조 무시)
    tab_cal, tab_month, tab_year = st.tabs(("📅 달력 (전체 조)", "A조 월간표", "A조 연간표"))
    with tab_month:
        a_team_month(store, entries, year, month, mobile, today)
    with tab_year:
        a_team_year(store, entries, year, mobile, today)
    with tab_cal:
        group_of = {r["이름"]: r["소속"] for r in dr.load_roster(store)}
        groups = st.multiselect("소속", dr.GROUPS, default=list(dr.GROUPS), key="leave_groups")
        who = st.text_input("이름 찾기", key="leave_name", placeholder="예: 이성호")

        def team(e):
            return group_of.get(e["name"]) or {"A": "A조", "B": "B조", "C": "C조", "D": "주간고정"}.get(e.get("team", ""), "")

        def shown(e):
            g = team(e)
            return (not g or g in groups) and (not who or who.strip() in e["name"])
        days = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)   # 일요일 시작 (앱 달력과 같음)
        month_entries = {d: [e for e in entries.get(d, []) if shown(e)] for week in days for d in week if d.month == month}

        chips = {}                       # (칩 키, 날짜) → 일정 — 누른 칩을 찾는다 (10/23)

        def chip(e, d):
            bg, fg = TONES[tone(e["kind"])]
            tag = SHORT.get(team(e), "")
            key = f"m:{e['id']}" if e.get("manual") else f"o:{e['name']}:{e['kind']}"
            chips[key, d.isoformat()] = e
            return (f"<span data-chip='{escape(key, quote=True)}' data-date='{d.isoformat()}' "
                    f"title='누르면 수정·삭제' style='display:inline-block;background:{bg};color:{fg};border:1px solid #e5e7eb;"
                    f"border-radius:6px;padding:1px 5px;margin:1px;font-size:.74rem;line-height:1.3'>"
                    f"{('<b>' + escape(tag) + '</b> ') if tag else ''}{escape(e['name'])} {escape(e['kind'])}"
                    f"{(' · ' + escape(e['note'])) if e.get('note') else ''}{' [직접 등록]' if e.get('manual') else ''}</span>")

        def day_head(d):
            red = is_off_day(d)
            teams = dr.teams_for(d)
            hol = holiday_name(d)
            mark = " style='outline:2px solid #2563eb;outline-offset:-2px'" if d == today else ""
            return (f"<div{mark}><span class='add' data-add='{d.isoformat()}' title='이 날짜에 일정 추가'>＋</span>"
                    f"<b style='color:{'#dc2626' if red else '#111827'}'>{d.day}</b>"
                    + (f" <span style='color:#dc2626;font-size:.7rem'>{escape(hol)}</span>" if hol else "")
                    + (" <span title='웨딩 있음' style='font-size:.72rem;background:#FCE7F3;color:#9D174D;border-radius:6px;padding:0 4px'>💒 웨딩</span>"
                       if d in weddings else "")
                    + f"<div style='font-size:.66rem;color:#6b7280'>주 {teams['주간조'][0]} · 야 {teams['야간조'][0]}</div></div>")
        legend = " ".join(f"<span style='background:{bg};color:{fg};border:1px solid #e5e7eb;border-radius:6px;"
                          f"padding:1px 6px;font-size:.75rem'>{name}</span>"
                          for name, (bg, fg) in (("연차·휴가 등(사고)", TONES["사고"]), ("반차", TONES["반차"]),
                                                 ("지원·대근", TONES["지원"]), ("교육·검진", TONES["교육"]),
                                                 ("입사·퇴사·편입", TONES["인사"])))
        st.markdown(legend + " <span style='font-size:.75rem;color:#6b7280'>· 주/야 = 그날 주간조·야간조</span>",
                    unsafe_allow_html=True)
        st.caption("일정 칩을 누르면 수정·삭제, 날짜 칸의 ＋를 누르면 그 날짜에 일정을 추가합니다. "
                   "원본(연차일정 파일) 일정을 고치거나 지우면 [직접 등록]으로 덮어쓰고, 새 연차일정 파일을 올리면 초기화됩니다.")
        if mobile:                       # 폰: 항목 있는 날만 날짜 목록 (빈 날은 위 '＋ 일정 추가')
            if st.button("＋ 일정 추가", key="leave_add_any", width="stretch"):
                open_leave_dialog(store, {"kind": "add", "date": (today if (today.year, today.month) == (year, month)
                                                                    else date(year, month, 1)).isoformat()}, {})
            html = "".join(f"<div style='background:#fff;color:#111827;border-radius:8px;padding:6px 8px;margin:4px 0'>"
                           f"{day_head(d)}{''.join(chip(e, d) for e in items)}</div>"
                           for d, items in month_entries.items() if items or d in weddings)
            if not html:
                st.caption("이 달에 표시할 항목이 없습니다.")
            else:
                leave_calendar(store, html, chips, f"m_{year}_{month}")
        else:                            # PC: 한 달 달력
            head = "".join(f"<th style='padding:4px;color:{'#dc2626' if i in (0, 6) else '#111827'}'>{w}</th>"
                           for i, w in enumerate("일월화수목금토"))
            body = ""
            for week in days:
                body += "<tr>" + "".join(
                    (f"<td style='vertical-align:top;border:1px solid #d1d5db;padding:4px;height:92px;"
                     f"background:{'#fff7f7' if is_off_day(d) else '#fff'}'>{day_head(d)}"
                     + "".join(chip(e, d) for e in month_entries.get(d, [])) + "</td>")
                    if d.month == month else "<td style='border:1px solid #e5e7eb;background:#f3f4f6'></td>"
                    for d in week) + "</tr>"
            leave_calendar(store, "<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;table-layout:fixed;"
                           "background:#fff;color:#111827'><tr style='background:#e5e7eb'>" + head + "</tr>" + body
                           + "</table></div>", chips, f"p_{year}_{month}")
        # 사람별 이번 달 합계
        counts: dict[str, Counter] = defaultdict(Counter)
        for d, items in month_entries.items():
            for e in items:
                counts[(team(e), e["name"])][tone(e["kind"])] += 1
        if counts:
            st.markdown("#### 이번 달 사람별")
            rows = [{"소속": g, "이름": n, "사고(연차·휴가 등)": c["사고"], "반차": c["반차"], "지원·대근": c["지원"],
                     "교육·검진": c["교육"], "인사": c["인사"], "기타": c["기타"]}
                    for (g, n), c in sorted(counts.items(), key=lambda x: (dr.GROUPS.index(x[0][0]) if x[0][0] in dr.GROUPS else 9, x[0][1]))]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---- A조 월간표·연간표 (2026-10-18 사용자 요청: 사람별 이번 달 합계 대신 월·연 단위로 정리, 다른 조 무시) ----
USE_DAYS = {"사고": 1.0, "반차": 0.5}         # 사용 일수: 연차·휴가 등 1일, 반차 0.5일


def a_team_members(store, start: date, end: date) -> list[str]:
    """그 기간에 A조였던 사람 (명단 시작·종료일 기준). 통제A → 대원 → CP 순."""
    order = {"통제A": 0, "대원": 1, "CP": 2}
    out = []
    for r in dr.load_roster(store):
        if r.get("소속") != "A조":
            continue
        s, e = r.get("시작"), r.get("종료")
        if (s and date.fromisoformat(s) > end) or (e and date.fromisoformat(e) < start):
            continue
        out.append((order.get(r.get("직책"), 3), r["이름"]))
    return [n for _, n in sorted(out, key=lambda x: x[0])]


def short_kind(kind: str) -> str:
    """칸 약자: 연차 '연', 오전반차 '전반', 오후반차 '후반', 교육 '교', 지원 '지' 등."""
    k = kind.replace(" ", "")
    if "반차" in k or "반야" in k:
        return "전" if ("오전" in k or "전반" in k) else "후" if ("오후" in k or "후반" in k) else "반"
    t = tone(kind)
    return {"교육": "교", "지원": "지"}.get(t, k[:2] if t == "인사" else k[:1] or "·")


def _a_team_items(entries, members, start: date, end: date) -> dict:
    """(이름, 날짜) → 그날 항목들 (A조 사람만, 기간 안)."""
    names = set(members)
    out = defaultdict(list)
    for d, items in entries.items():
        if start <= d <= end:
            for e in items:
                if e["name"] in names:
                    out[(e["name"], d)].append(e)
    return out


def _use(items) -> float:
    """그날 사용 일수 (같은 날 여러 항목이면 큰 쪽)."""
    return max((USE_DAYS.get(tone(e["kind"]), 0.0) for e in items), default=0.0)


def _num(x: float) -> str:
    return "" if not x else (f"{x:g}")


_TABLE_CSS = ("<style>.lv{border-collapse:collapse;width:100%;table-layout:fixed;background:#fff;color:#111827;font-size:.74rem}"
              ".lv th,.lv td{border:1px solid #e5e7eb;text-align:center;padding:3px 0;overflow:hidden;white-space:nowrap}"
              ".lv th{background:#f3f4f6;font-weight:600}.lv td.name,.lv th.name{text-align:left;padding-left:4px;width:4.2em}"
              ".lv .off{color:#dc2626;background:#fff7f7}.lv .today{outline:2px solid #2563eb;outline-offset:-2px}"
              ".lv td.sum{font-weight:700;background:#f8fafc}.lv th.sum{width:3.2em}</style>")


def a_team_month(store, entries, year: int, month: int, mobile: bool, today: date) -> None:
    """A조 사람 × 날짜. 칸 = 약자·색(연차 빨강·반차 주황·교육 보라·지원 파랑), 오른쪽 사용 일수·연차·반차·교육·지원."""
    last = calendar.monthrange(year, month)[1]
    start, end = date(year, month, 1), date(year, month, last)
    members = a_team_members(store, start, end)
    items = _a_team_items(entries, members, start, end)
    st.caption(f"{year}년 {month}월 · A조 {len(members)}명 · 사용 일수 = 연차·휴가 등 1일, 반차 0.5일 · 다른 조 제외 · "
               "칸: 연=연차(빨강) · 전/후=오전·오후 반차(주황) · 교=교육(보라) · 지=지원(파랑)"
               + ("" if mobile else " · 칸에 마우스를 올리면 원문"))
    rows = []
    for n in members:
        days = {d: items[(n, d)] for (m, d) in items if m == n}
        c = Counter(tone(e["kind"]) for its in days.values() for e in its)
        rows.append((n, days, c, sum(_use(v) for v in days.values())))
    if mobile:                                    # 폰: 가로 스크롤 없이 사람별 한 줄
        for n, days, c, used in rows:
            detail = " · ".join(f"{d.day}일 {'/'.join(short_kind(e['kind']) for e in its)}" for d, its in sorted(days.items()))
            st.markdown(f"<div style='background:#fff;color:#111827;border-radius:8px;padding:6px 8px;margin:3px 0;font-size:.85rem'>"
                        f"<b>{escape(n)}</b> · 사용 <b>{_num(used) or 0}일</b>"
                        + (f"<div style='font-size:.78rem;color:#374151'>{escape(detail)}</div>" if detail else "")
                        + "</div>", unsafe_allow_html=True)
        return
    head = "<th class='name'>이름</th>" + "".join(
        f"<th class='{'off' if is_off_day(date(year, month, d)) else ''}{' today' if date(year, month, d) == today else ''}'>"
        f"{d}<br><span style='font-weight:400'>{'월화수목금토일'[date(year, month, d).weekday()]}</span></th>"
        for d in range(1, last + 1)) + "".join(f"<th class='sum'>{h}</th>" for h in ("사용", "연차", "반차", "교육", "지원"))
    body = ""
    for n, days, c, used in rows:
        cells = f"<td class='name'><b>{escape(n)}</b></td>"
        for d in range(1, last + 1):
            day = date(year, month, d)
            its = days.get(day, [])
            off = " off" if is_off_day(day) else ""
            if its:
                bg, fg = TONES[tone(its[0]["kind"])]
                tip = " / ".join(e["kind"] + (f" · {e['note']}" if e.get("note") else "") for e in its)
                cells += (f"<td class='{off.strip()}' title='{escape(tip)}' style='background:{bg};color:{fg};font-weight:700'>"
                          f"{escape('/'.join(short_kind(e['kind']) for e in its))}</td>")
            else:
                cells += f"<td class='{off.strip()}'></td>"
        cells += "".join(f"<td class='sum'>{_num(v)}</td>" for v in (used, c["사고"], c["반차"], c["교육"], c["지원"]))
        body += f"<tr>{cells}</tr>"
    st.markdown(_TABLE_CSS + "<div style='overflow-x:auto'><table class='lv'><tr>" + head + "</tr>" + body + "</table></div>",
                unsafe_allow_html=True)


def a_team_year(store, entries, year: int, mobile: bool, today: date) -> None:
    """A조 사람 × 1~12월 사용 일수(연차 1·반차 0.5)와 연간 합계, 오른쪽 연차·반차·교육·지원 횟수."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    members = a_team_members(store, start, end)
    items = _a_team_items(entries, members, start, end)
    st.caption(f"{year}년 · A조 {len(members)}명 · 월별 숫자 = 사용 일수(연차·휴가 등 1일, 반차 0.5일) · 다른 조 제외")
    head = "<th class='name'>이름</th>" + "".join(
        f"<th class='{'today' if (year, m) == (today.year, today.month) else ''}'>{m}월</th>" for m in range(1, 13)) \
        + "<th class='sum'>합계</th>" + ("" if mobile else "".join(f"<th class='sum'>{h}</th>" for h in ("연차", "반차", "교육", "지원")))
    body, totals = "", [0.0] * 12
    for n in members:
        per = [0.0] * 12
        c = Counter()
        for (m, d), its in items.items():
            if m == n:
                per[d.month - 1] += _use(its)
                c.update(tone(e["kind"]) for e in its)
        totals = [a + b for a, b in zip(totals, per)]
        cells = f"<td class='name'><b>{escape(n)}</b></td>" + "".join(f"<td>{_num(v)}</td>" for v in per)
        cells += f"<td class='sum'>{_num(sum(per)) or 0}</td>"
        if not mobile:
            cells += "".join(f"<td class='sum'>{_num(c[k])}</td>" for k in ("사고", "반차", "교육", "지원"))
        body += f"<tr>{cells}</tr>"
    foot = ("<tr><td class='name'><b>A조 계</b></td>" + "".join(f"<td class='sum'>{_num(v)}</td>" for v in totals)
            + f"<td class='sum'>{_num(sum(totals)) or 0}</td>" + ("" if mobile else "<td class='sum'></td>" * 4) + "</tr>")
    st.markdown(_TABLE_CSS + "<div style='overflow-x:auto'><table class='lv'><tr>" + head + "</tr>" + body + foot
                + "</table></div>", unsafe_allow_html=True)
