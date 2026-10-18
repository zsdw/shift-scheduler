"""보안근무명령서 탭: PC·폰 공통 날짜 선택 및 원본 양식 미리보기."""
from datetime import date, timedelta
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
import mobile_ui
from history_ui import store_dir
from night_shift import order_source, security_order, daily_report as dr

_CALENDAR=components.declare_component('order_calendar',path=str(Path(__file__).resolve().parent/'night_shift/calendar_picker'))


def calendar():
    from night_shift.calendar_info import HOLIDAYS, PATTERN_START
    chosen=_CALENDAR(data={'selected':st.session_state['order_day'].isoformat(),'today':date.today().isoformat(),
        'saved':sorted(d.isoformat() for d in order_source.days_with_data(store_dir())),'pattern_start':PATTERN_START.isoformat(),'holidays':{d.isoformat():name for d,name in HOLIDAYS.items()},
        'year_from':2025,'year_to':max(2028,date.today().year+1)},key='order_calendar',default=None)
    if isinstance(chosen,dict) and chosen.get('nonce')!=st.session_state.get('order_calendar_nonce'):
        st.session_state['order_calendar_nonce']=chosen.get('nonce')
        st.session_state['order_day']=date.fromisoformat(chosen['date'])
        st.rerun()


def name_fix_editor(store,day,sources):
    """편성표 엑셀의 번호 이름 오기를 명령서에서만 바로잡는다 (원본 엑셀은 그대로, PC·폰)."""
    import pandas as pd
    fixes=order_source.load_name_fixes(store).get(day.isoformat(),{})
    with st.expander('편성표 번호 이름 고치기',expanded=bool(fixes)):
        st.caption('편성표에 번호 이름이 잘못 적힌 경우(예: 1번·6번 모두 만년) 실제 이름으로 바꿉니다. 원본 엑셀은 바꾸지 않습니다.')
        for shift,source in sources.items():
            current={**source['names'],**fixes.get(shift,{})}
            frame=pd.DataFrame([{'번호':int(n),'편성표':source['names'][n],'실제 이름':current[n]}
                                for n in sorted(source['names'],key=int)])
            edited=st.data_editor(frame,disabled=['번호','편성표'],hide_index=True,width='stretch',
                                  key=f'order_names_{day}_{shift}')
            change={str(r['번호']):str(r['실제 이름']).strip() for r in edited.to_dict('records')
                    if str(r['실제 이름']).strip() and str(r['실제 이름']).strip()!=source['names'][str(r['번호'])]}
            if change!=fixes.get(shift,{}) and st.button(f"{'주간' if shift=='day' else '야간'} 이름 고침 저장",key=f'order_names_save_{day}_{shift}'):
                order_source.save_name_fix(store,day,shift,change); st.rerun()


def page():
    store=store_dir()
    st.session_state.setdefault('order_day',date.today())
    mobile=mobile_ui.is_mobile()
    if not mobile:
        with st.sidebar:
            st.header('명령서 날짜'); calendar()
    st.title('보안근무명령서')
    if mobile: calendar()
    day=st.session_state['order_day']
    import date_check_ui                         # 연차일정·일보·근무표·명령서 대조 결과 (2026-10-07)
    date_check_ui.banner(day)
    a,b,c=st.columns([1,5,1])
    if a.button('◀',key='order_prev'):
        st.session_state['order_day']=day-timedelta(days=1); st.rerun()
    b.markdown(f"**{day:%Y년 %m월 %d일}({'월화수목금토일'[day.weekday()]})**")
    if c.button('▶',key='order_next'):
        st.session_state['order_day']=day+timedelta(days=1); st.rerun()
    if not order_source.document_available(store,day):   # 자료 있는 날은 모두 (2026-10-11)
        st.caption('이 날짜는 편성표 자료(올린 엑셀·프로그램 저장본)가 없습니다.')
        return
    with st.expander('자료 폴더 · 최신 파일',expanded=False):
        st.caption(str(order_source.SOURCE_DIR))
        st.caption('이 폴더에 최신 편성표 엑셀과 연차일정 텍스트를 넣고 날짜를 선택하면 반영됩니다.')
        if st.button('최신 자료 다시 읽기',key='order_refresh'): st.rerun()
    try:
        sources=dict(order_source.reference_sources(store,day))
        if sources:st.caption('참조 편성표: '+next(iter(sources.values())).get('file',''))
        else:st.caption('최신 참조 자료에 이 날짜의 편성표가 없습니다.')
    except (OSError,ValueError,KeyError) as exc:
        st.warning(f'편성표를 읽지 못했습니다: {exc}');sources={}
    program=order_source.saved_day_source(store,day)   # 저장된 프로그램 근무표가 진짜 근무표 (2026-10-07 사용자 확정)
    if program:
        sources['day']=program
        st.caption(f"주간 시간표: {program['sheet']}")
    night=order_source.saved_night_source(store,day)
    if night:
        sources['night']=night
        st.caption('야간 시간표: 저장된 프로그램 실제 근무표')
    for shift,source in sources.items():
        st.caption(f"{'주간' if shift=='day' else '야간'}: {source['team']}조 · {source['sheet']}")
    excel_only={k:v for k,v in sources.items() if not v.get('program')}
    if excel_only:
        name_fix_editor(store,day,excel_only)
    sources=order_source.apply_name_fixes(sources,store,day)
    sources=order_source.cp_sources(sources,store,day)
    from night_shift.document_basis import report_for
    report=report_for(store,day,sources)
    if report is None:
        st.info('근무표와 연차일정이 달라 작성 기준을 선택해야 명령서를 작성할 수 있습니다.')
        return
    from night_shift.document_basis import sources_for_report
    sources=sources_for_report(sources,report,dr.load_roster(store))
    book,ws,warnings=security_order.build(day,store,sources,report=report)
    if warnings:
        with st.expander(f'확인할 내용 {len(warnings)}건',expanded=True):
            for message in warnings: st.markdown('- '+message)
    st.markdown(security_order.sheet_html(ws),unsafe_allow_html=True)
    st.download_button('보안근무명령서 엑셀 다운로드',security_order.excel_bytes(book),
                       file_name=f'보안근무명령서_{day.isoformat()}.xlsx',
                       mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='order_download')
