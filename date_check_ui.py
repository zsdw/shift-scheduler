"""날짜를 고르면 페이지 맨 위에 문서 대조 결과 (연차일정·근태일보·근무표·근무명령서, PC·폰 공통).

PC는 오른쪽 여백에 건마다 '어느 쪽이 맞나' 처리 칸, 폰은 각 건 바로 아래 (2026-10-07 사용자 요청).
"""
from datetime import date
from html import escape

import streamlit as st

from history_ui import store_dir

TONE = {"error": ("#fee2e2", "#991b1b", "#ef4444"), "warn": ("#fef3c7", "#92400e", "#f59e0b"),
        "auto": ("#f1f5f9", "#334155", "#94a3b8")}


def _card(issue) -> str:
    bg, fg, bar = TONE.get(issue["level"], TONE["auto"])
    sources = " · ".join(f"{escape(a)}: <b>{escape(b)}</b>" for a, b in issue["sources"])
    return (f"<div style='background:{bg};color:{fg};border-left:6px solid {bar};padding:8px 12px;border-radius:8px;"
            f"margin:2px 0 6px;font-size:.92rem;line-height:1.45'><b>📌 {escape(issue['where'])}</b><br>{escape(issue['message'])}"
            + (f"<div style='font-size:.8rem;opacity:.85;margin-top:2px'>{sources}</div>" if sources else "") + "</div>")


def _controls(store, day, issue, where) -> None:
    from night_shift import date_check
    choices = issue["choices"]
    if not choices:
        return
    key = f"dc_{day}_{issue['key']}"
    ids = [c["id"] for c in choices]
    label = {c["id"]: c["label"] for c in choices}
    pick = where.radio("어느 쪽이 맞나요?", ids, index=ids.index(issue["default"]) if issue["default"] in ids else 0,
                       format_func=label.get, key=key + "_pick", label_visibility="collapsed")
    status = None
    if pick == "fix":
        fix = next(c for c in choices if c["id"] == "fix")
        options = list(date_check.FIX_STATUSES)
        status = where.selectbox("고칠 상태", options, index=options.index(fix["status"]) if fix["status"] in options else 0,
                                 key=key + "_status")
    if where.button("적용", key=key + "_apply", type="primary" if issue["level"] == "error" else "secondary"):
        st.session_state["dc_flash"] = date_check.apply(store, day, issue, pick, status)
        st.rerun()


def banner(day: date) -> None:
    from night_shift.order_source import document_available
    from night_shift import document_basis
    store=store_dir()
    from night_shift.daily_report import retiring     # 퇴사 예정 안내: 마지막 근무일 7일 전부터 당일까지 (2026-10-12)
    for name,last in retiring(store,day):
        left=(last-day).days
        when='오늘 마지막 근무' if left==0 else f'D-{left}'
        st.markdown(f"<div style='background:#f3f4f6;color:#374151;border-left:6px solid #6b7280;padding:6px 12px;"
                    f"border-radius:8px;margin:2px 0 6px;font-size:.9rem'>👋 퇴사 예정: <b>{name}</b> — "
                    f"{last:%m/%d} 마지막 근무 ({when}). 다음 날부터 일보·근무 편성·명령서 명단에서 빠집니다.</div>",
                    unsafe_allow_html=True)
    if not document_available(store,day):             # 명령서·일보를 띄우는 날은 모두 대조 (2026-10-11)
        return
    try:
        sources,issues,stamp,basis=document_basis.state(store,day)
    except (OSError,ValueError,KeyError) as exc:
        st.caption(f'문서 자료를 읽지 못했습니다: {exc}')
        return
    if not issues:
        return
    if basis:
        st.caption('문서 작성 기준: '+('연차일정표' if basis=='leave' else '근무표'))
        if st.button('작성 기준 다시 선택',key=f'dc_basis_reset_{day}'):
            document_basis.save(store,day,'',None);st.rerun()
        return
    st.warning(f"{day:%m/%d} 근무표와 연차일정이 다릅니다. 어느 자료를 기준으로 문서를 작성할까요?")
    for issue in issues:
        st.markdown(_card(issue),unsafe_allow_html=True)
    pick=st.radio('작성 기준',['leave','schedule'],index=None,
                  format_func=lambda x:'연차일정표 기준' if x=='leave' else '근무표 기준',key=f'dc_basis_{day}_{stamp}')
    st.caption('선택한 기준은 일보와 명령서에 함께 적용됩니다. 원본 일정과 근무표는 그대로 유지합니다.')
    if st.button('선택한 기준으로 작성',disabled=pick is None,key=f'dc_basis_apply_{day}_{stamp}',type='primary'):
        document_basis.save(store,day,stamp,pick);st.rerun()
