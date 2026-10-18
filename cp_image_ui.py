"""PC·폰 공통 CP 월간 이미지 인식·인원별 확인·최종 저장."""
import hashlib
from datetime import date
from calendar import monthrange
import pandas as pd
import streamlit as st
from history_ui import store_dir
from night_shift import cp_image,cp_schedule

def render(data,filename,message_key='leave_upload_message'):
    digest=hashlib.sha256(data).hexdigest();key='cp_image_'+digest
    st.image(data,caption=filename)
    if st.button('이미지 다시 읽기',key=key+'_read'):st.session_state.pop(key,None)
    if key not in st.session_state:
        try:
            with st.spinner('CP 월간 표의 날짜·이름·근무 배정을 읽는 중입니다…'):
                st.session_state[key]=cp_image.parse_image(data)
        except (ValueError,OSError) as exc:st.error(str(exc));return
    draft=st.session_state[key]
    a,b=st.columns(2)
    year=int(a.number_input('연도',2024,2035,date.today().year,key=key+'_year'))
    month=int(b.number_input('월',1,12,draft['month'] or date.today().month,key=key+'_month'))
    for person in draft['rows']:
        for day in range(1,monthrange(year,month)[1]+1):person.setdefault(str(day),'확인 필요')
    st.caption('주1~3·야1~3은 CP 번호입니다. 읽지 못한 칸은 확인 필요로 표시합니다. 인원별로 원본과 대조한 뒤 저장하세요.')
    if draft['warnings']:
        with st.expander('인식 확인 사항'):
            for warning in draft['warnings']:st.caption(warning)
    selected=st.selectbox('확인할 근무자',range(len(draft['rows'])),format_func=lambda i:draft['rows'][i]['이름'],key=key+'_person')
    row=draft['rows'][selected]
    row['이름']=st.text_input('근무자 이름',row['이름'],key=key+f'_name_{selected}')
    days=range(1,monthrange(year,month)[1]+1)
    frame=pd.DataFrame([{'날짜':d,'배정':row.get(str(d),'확인 필요')} for d in days])
    edited=st.data_editor(frame,hide_index=True,width='stretch',disabled=['날짜'],key=key+f'_cells_{selected}_{year}_{month}',
        column_config={'배정':st.column_config.SelectboxColumn(options=['','주1','주2','주3','야1','야2','야3','연차','휴무','대휴','휴','병가','휴가','비번','-','—','확인 필요'])})
    row.update({str(int(r['날짜'])):r['배정'] for r in edited.to_dict('records')})
    verified=st.checkbox('연도·월·모든 근무자의 이름과 날짜별 배정을 이미지 원본과 확인했습니다.',key=key+'_verified')
    if st.button('CP 이미지 확인본 저장',disabled=not verified,key=key+'_save',type='primary'):
        try:
            entries=cp_image.entries_from_rows(year,month,draft['rows'])
            cp_schedule.replace_uploaded(store_dir(),entries,{f'{year}-{month:02d}'},data,filename)
        except (ValueError,OSError) as exc:st.error(f'저장 전 수정이 필요합니다: {exc}');return
        st.session_state[message_key]=f'{year}년 {month}월 CP 이미지 확인본 저장 — 날짜별 근무표·명령서에 자동 적용합니다.'
        st.rerun()
