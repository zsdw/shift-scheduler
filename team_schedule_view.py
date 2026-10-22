"""조별 출력과 항목별 요약 화면. 수정 기능·규칙 경고 없음."""
from datetime import date
from team_schedule_ui import sources,table_html
from team_schedule_analysis import people,hours,metrics,totals,details


def summary(rows,key):
    import streamlit as st
    import pandas as pd
    groups={'피로도·근무':('근무자','근무횟수','피로도','실근무'),
            '휴게':('근무자','휴게','대기','막휴게','대폭휴게'),
            '순찰':('근무자','순찰','상층','중층','하층'),
            '차단봉':('근무자','차단봉 설치','차단봉 철수')}
    item=st.segmented_control('요약 항목',list(groups),default='피로도·근무',key=key) or '피로도·근무'
    st.dataframe(pd.DataFrame(rows)[list(groups[item])],hide_index=True,width='stretch')


def calculations(source,mode):
    import streamlit as st
    import pandas as pd
    rows=details(source,mode)
    with st.expander('근무자별 피로도 계산 내역'):
        token=st.selectbox('근무자',list(people(source)),format_func=lambda n:f'{n} {people(source)[n]}',key=f'team_calc_{source["team"]}')
        selected=[r for r in rows if r['번호']==token]
        a=sum(r['입식점수'] for r in selected);b=sum(r['좌식점수'] for r in selected)
        c=sum(r['순찰점수'] for r in selected);total=sum(r['피로도'] for r in selected)
        st.markdown(f'**{people(source)[token]} · {mode} {total}점** = 입식 {a} + 좌식 {b} + 순찰 {c} + 차단봉 {total-a-b-c}')
        st.dataframe(pd.DataFrame([{k:r[k] for k in ('시간','표시','계산','피로도')} for r in selected]),hide_index=True,width='stretch')
        st.caption('야간 유도리: I1 22~03시 휴게성. 주말·공휴일 주간 유도리: G2 휴게성. 평일 주간은 FM·유도리 계산이 같습니다. 포스트 겸임 차단봉은 원래 포스트 점수로 계산합니다.')


def downloads(source,store):
    import streamlit as st
    import pandas as pd
    from team_schedule_export import export
    from pathlib import Path
    import json
    source=dict(source)
    marker=Path(store)/'latest_upload.json'
    if marker.exists():
        original=json.loads(marker.read_text(encoding='utf-8'))
        path=Path(original.get('path',''))
        if original.get('file')==source.get('file') and path.is_file():
            source['_original_path']=str(path)
            source['_original_stamp']=path.stat().st_mtime_ns
            from night_shift.source_attachment import render_button
            render_button({'source':'excel','source_attachment':str(path),'source_file':source['file']},key=f'team_original_{source["team"]}_{source["day"]}')
    name=f'{source["day"]}_{source["team"]}조_{"야간" if source["shift"]=="night" else "주간"}'
    cached=st.cache_data(show_spinner=False)(export)
    for kind,label,mime in (('png','🖼 현장 양식 이미지 다운로드','image/png'),
                            ('xlsx','📊 현장 양식 엑셀 다운로드','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')):
        try:st.download_button(label,cached(source,kind),file_name=f'{name}.{kind}',mime=mime,key=f'{name}_{kind}',width='stretch')
        except (OSError,ValueError,KeyError) as exc:st.error(f'{label}: {exc}')
    frame=pd.DataFrame([{'시간':f'{h:02}:00',**source['cells'].get(str(h),{})} for h in hours(source)])
    st.download_button('근무표 CSV 다운로드',frame.to_csv(index=False).encode('utf-8-sig'),file_name=f'{name}.csv',mime='text/csv')


def page(team,store):
    import streamlit as st
    import pandas as pd
    data=sources(store,team)
    selected=st.date_input('날짜',value=st.session_state.get('shift_date',date.today()),key='team_view_date')
    available=[shift for iso,shift in data if iso==selected.isoformat()]
    st.subheader(f'{selected:%Y년 %m월 %d일} · {team}조')
    mode=st.segmented_control('분석 기준',('FM','유도리'),default='FM',key='team_analysis_mode') or 'FM'
    if available:
        shift=st.segmented_control('근무',available,default=available[0],format_func=lambda s:'야간' if s=='night' else '주간',key=f'team_shift_{team}_{selected}') or available[0]
        source=data[selected.isoformat(),shift]
        st.caption(' · '.join(f'{n} {name}' for n,name in people(source).items()))
        st.markdown(table_html(source,mode),unsafe_allow_html=True)
        if source.get('cp'):st.caption(' · '.join(f'CP{n} {name}' for n,name in source['cp'].items()))
        st.caption(f"출처: {source.get('file','')} · {source.get('sheet','')}")
        with st.expander('현장 양식 출력·다운로드'):downloads(source,store)
        st.markdown(f'**당일 요약 · {mode}**');summary(metrics(source,mode),'team_daily_summary')
        calculations(source,mode)
    else:st.info('이 날짜의 해당 조 근무표 자료가 없습니다.');shift='night'
    st.markdown(f'**기간별 요약 · {mode}**')
    period=st.date_input('집계 기간',value=(selected.replace(day=1),selected),key=f'team_metrics_period_{selected}')
    kind=st.selectbox('집계 근무',('night','day'),index=0 if shift=='night' else 1,format_func=lambda s:'야간' if s=='night' else '주간',key=f'team_metrics_kind_{team}_{selected}')
    if len(period)==2:
        records=[s for (iso,k),s in sorted(data.items()) if k==kind and period[0]<=date.fromisoformat(iso)<=period[1]]
        if records:
            rows=totals(records,mode);summary(rows,'team_period_summary')
            st.download_button('집계 CSV 다운로드',pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),file_name=f'{team}조_{kind}_{mode}_{period[0]}_{period[1]}.csv',mime='text/csv')
            st.caption(f'자료 {len(records)}근무 집계 · 주간과 야간은 별도 집계')
        else:st.caption('선택 기간에 집계할 자료가 없습니다.')
