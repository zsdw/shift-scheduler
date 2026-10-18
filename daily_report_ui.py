"""근태관리 일보 탭 (2026-10-06): 프로그램 맨 위 '📋 근태관리 일보' 탭. 근무표 화면과 분리. PC·폰 공통."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import streamlit.components.v1 as components
from pathlib import Path

from history_ui import store_dir
from night_shift import wedding
from night_shift import daily_report as dr

# 근무표 화면과 같은 달력 부품 (night_shift/calendar_picker)
_CALENDAR = components.declare_component(
    "report_calendar", path=str(Path(__file__).resolve().parent / "night_shift" / "calendar_picker"))


def writing_day(now: datetime | None = None) -> date:
    """지금 쓰는 일보 날짜: D일 일보는 D-1일 밤 야간조가 쓴다 → 07시 이후면 내일, 00~07시면 오늘 (2026-10-06)."""
    now = now or datetime.now()
    return (now - timedelta(hours=7)).date() + timedelta(days=1)


def _shift_day(delta: int) -> None:
    st.session_state["daily_report_day"] = st.session_state["daily_report_day"] + timedelta(days=delta)


def _calendar(store) -> None:
    """근무표 화면과 같은 달력 (같은 부품, 2026-10-06 사용자 요청). 날짜를 누르면 그 날짜 일보."""
    from history_ui import day_store_dir
    from night_shift import history_store
    from night_shift.calendar_info import HOLIDAYS, PATTERN_START
    saved = sorted(set(history_store.list_dates(store)) | set(history_store.list_dates(day_store_dir())))
    picked = _CALENDAR(data={
        "selected": st.session_state["daily_report_day"].isoformat(), "today": date.today().isoformat(),
        "saved": [d.isoformat() for d in saved], "pattern_start": PATTERN_START.isoformat(),
            "weddings": [d.isoformat() for d in wedding.load(store_dir())],   # 💒 웨딩 있는 날 (2026-10-13)
        "holidays": {d.isoformat(): name for d, name in HOLIDAYS.items()},
        "year_from": 2025, "year_to": max(2028, date.today().year + 1),
    }, key="report_calendar", default=None)
    if isinstance(picked, dict) and picked.get("nonce") != st.session_state.get("report_calendar_nonce"):
        st.session_state["report_calendar_nonce"] = picked.get("nonce")
        st.session_state["daily_report_day"] = date.fromisoformat(picked["date"])
        st.rerun()


def page() -> None:
    import mobile_ui
    store = store_dir()
    st.session_state.setdefault("daily_report_day", writing_day())
    mobile = mobile_ui.is_mobile()
    if not mobile:                               # PC: 근무표처럼 사이드바에 달력
        with st.sidebar:
            st.header("일보 날짜")
            _calendar(store)
    st.title("근태관리 일보")
    if mobile:                                   # 폰: 본문 맨 위에 달력
        _calendar(store)
    day = st.session_state["daily_report_day"]
    import date_check_ui                         # 연차일정·일보·근무표·명령서 대조 결과 (2026-10-07)
    date_check_ui.banner(day)
    c0, c1, c3, c2 = st.columns([0.5, 1.2, 0.5, 2])
    c0.button("◀", key="daily_prev", on_click=_shift_day, args=(-1,), help="전날 일보")
    c1.markdown(f"**{day:%Y-%m-%d}({'월화수목금토일'[day.weekday()]})**"
                + ("  \n📌 오늘 밤 야간조가 쓰는 일보" if day == writing_day() else ""))
    c3.button("▶", key="daily_next", on_click=_shift_day, args=(1,), help="다음날 일보")
    with c2:
        from leave_view_ui import upload_box
        upload_box(store, "daily_report_leave")
    render(day, store)


def render(day: date, store=None) -> None:
    from night_shift.order_source import document_available
    store = store or store_dir()
    if not document_available(store, day):           # 명령서와 같은 날짜 (2026-10-11 사용자 요청)
        st.caption('이 날짜는 편성표 자료(올린 엑셀·프로그램 저장본)가 없습니다.')
        return
    roster = dr.load_roster(store)
    entries = dr.entries_for(store, day)
    from night_shift.document_basis import report_for
    report = report_for(store,day)
    if report is None:
        st.info('근무표와 연차일정이 달라 작성 기준을 선택해야 일보를 작성할 수 있습니다.')
        return
    teams = report["teams"]
    st.markdown(f"**{day:%Y년 %m월 %d일}({'월화수목금토일'[day.weekday()]})** · 주간조 {teams['주간조']} · "
                f"야간조 {teams['야간조']} · 휴무조 {teams['휴무조']}"
                + (" · 🔴 주말·공휴일(주간고정·안내·주차 휴무)" if report["off_day"] else ""))
    rows = report["rows"]
    st.caption('작성 기준: '+{'leave':'연차일정표','schedule':'근무표','matched':'연차일정표·근무표 대조'}[report['document_basis']])
    st.caption(f"작성자: {report['writer']} · {report['writer_from']}")
    if entries:
        st.caption("연차일정: " + " / ".join(f"{e['name']} {e['kind']}" for e in entries))
    sheet = st.container()
    sheet.markdown(dr.sheet_html(report, rows), unsafe_allow_html=True)
    with sheet.expander("👥 조별 근무자 (A·B·C조·주간고정)", expanded=False):   # 일보 표 바로 아래 (2026-10-06)
        teams_now = {v: k for k, v in teams.items()}
        st.dataframe(pd.DataFrame([
            {"조": g + (f" ({teams_now[g]})" if g in teams_now else ""), "인원": f"{m['인원']}/{m['T/O']}",
             "조장": m["조장"], "대원": ", ".join(m["대원"]), "CP": ", ".join(m["CP"])}
            for g, m in dr.team_members(day, roster).items()]), hide_index=True, width="stretch")
    for line in report["checks"]:
        st.warning("확인 필요: " + line)
    st.caption("휴무·지원 등 추가 일정은 연차일정 탭에서 직접 등록하세요. "
               "기준: 출근 안 한 사람만 사고, 반차·교육·입사·퇴사는 비고만, 지원·대근은 원래 소속에서 출근으로 셈.")
    st.download_button("⬇ 근태관리 일보 엑셀 다운로드", dr.to_excel(report, rows),
                       file_name=f"근태관리일보_{day}.xlsx", key=f"daily_report_dl_{day}", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with st.expander("명단 · 입사/퇴사일 수정", expanded=False):
        st.caption("소속: 주간고정 / A조 / B조 / C조 / 안내 / 주차. 시작·종료일(YYYY-MM-DD)은 그 날짜 포함, 비우면 계속. "
                   "결원 = T/O − 그날 명단 인원. 조 교대는 A조 달력(주·주·야·야·휴·휴) 기준.")
        table = pd.DataFrame([{k: r.get(k, "") or "" for k in ("이름", "소속", "직책", "시작", "종료")} for r in roster])
        new = st.data_editor(table, hide_index=True, width="stretch", num_rows="dynamic", key="daily_roster_edit",
                             column_config={"소속": st.column_config.SelectboxColumn(options=dr.GROUPS, required=True)})
        if st.button("명단 저장", key="daily_roster_save"):
            cleaned = [{k: str(v).strip() for k, v in r.items() if str(v).strip() not in ("", "None", "nan")}
                       for _, r in new.iterrows()]
            cleaned = [r for r in cleaned if r.get("이름") and r.get("소속")]
            try:
                for r in cleaned:
                    for k in ("시작", "종료"):
                        if r.get(k):
                            date.fromisoformat(r[k][:10])
            except ValueError:
                st.error("시작·종료일은 2026-10-06처럼 적어 주세요.")
            else:
                dr.save_roster(store, cleaned)
                st.success(f"명단 {len(cleaned)}명을 저장했습니다.")
                st.rerun()
