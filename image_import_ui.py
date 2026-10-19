"""Same image review flow on PC and mobile, independent of selected schedule page."""
from dataclasses import replace
from datetime import date
from pathlib import Path
import re
import pandas as pd
import streamlit as st
from history_ui import store_dir,day_store_dir
from night_shift import schedule_image_import as images

LABELS={'day':'평일 주간','weekend_day':'주말·공휴일 주간','night':'야간'}

def render_image_review(file,data,digest,reanalyze=False):
    key='image_review_'+digest[:12]
    cached=st.session_state.get('schedule_image_draft')
    st.image(data,caption='업로드 원본 — 제목·시간·이름·배정을 아래 표와 대조하세요.',width='stretch')
    if reanalyze or not cached or cached[0]!=digest:
        try:
            with st.spinner('제목·시간대를 구분하고 이름·배정을 읽는 중입니다…'):
                draft=images.roster_repair(images.parse_image(data),store_dir())
            st.session_state['schedule_image_draft']=(digest,draft)
            if reanalyze:
                for widget_key in list(st.session_state):
                    if widget_key.startswith(key+'_'):del st.session_state[widget_key]
        except (ValueError,OSError,RuntimeError) as exc:
            st.error(str(exc));return
    draft=st.session_state['schedule_image_draft'][1]
    st.success(f'자동 구분: {LABELS[draft.kind]} · 근무조 {draft.team or "미확인"}')
    st.caption(draft.evidence)
    day=st.date_input('원본 근무 날짜',value=draft.day,key=key+'_date')
    team=st.selectbox('원본 근무조',['확인 필요','A','B','C','D'],index=['확인 필요','A','B','C','D'].index(draft.team or '확인 필요'),key=key+'_team')
    kind=images.kind_for(day,'night' if draft.kind=='night' else 'day')
    target=store_dir() if kind=='night' else store_dir()/'weekend_day' if kind=='weekend_day' else day_store_dir()
    if day:
        current=images.fingerprint(target,day);snap=key+'_snapshot_'+str(target)+'_'+str(day)
        if snap not in st.session_state:st.session_state[snap]=current
    st.caption(f'저장 구분: {LABELS[kind]} — 현재 보고 있는 화면의 날짜·종류와 무관하게 저장합니다.')
    if day and day.year not in (2026,2027) and kind!='night':
        st.error('이 연도의 공휴일 자료가 없습니다. 주말·공휴일 여부를 확인할 수 있는 연도(2026·2027)를 선택하세요.');return
    for warning in draft.warnings:
        if not re.match(r"^\d{2}:\d{2} [^:]+:",warning):
            st.warning(warning)
    st.write('**번호별 이름 확인·수정**')
    names=st.data_editor(pd.DataFrame([{'번호':p,'이름':n} for p,n in draft.mapping.items()]),
                         disabled=['번호'],hide_index=True,width='stretch',key=key+'_names')
    mapping={str(r['번호']):str(r['이름']).strip() for r in names.to_dict('records')}
    extras={}
    if draft.extra_names:
        cp=st.data_editor(pd.DataFrame([{'번호':p,'이름':n} for p,n in draft.extra_names.items()]),
                          disabled=['번호'],hide_index=True,width='stretch',key=key+'_cp_names')
        extras={str(r['번호']):str(r['이름']).strip() for r in cp.to_dict('records')}
    st.write('**시간별 배정 확인·수정**')
    st.caption('확인 필요 칸은 원본을 보고 수정하세요. 번호는 점(.)으로 구분합니다. 원본에 없는 빈칸은 그대로 두세요. 휴게·근무불가를 자동 추정하지 않습니다.')
    revision=st.session_state.get(key+'_revision',0)
    rows=st.data_editor(pd.DataFrame(draft.rows),hide_index=True,width='stretch',key=key+'_cells_'+str(revision)).fillna('').to_dict('records')
    from night_shift.newcomers import detect
    newcomer_info=detect(store_dir(),day,rows,mapping) if day else {}
    newcomers=list(newcomer_info)
    for number,evidence in newcomer_info.items():st.info(f'{number}번 {mapping[number]}: 신규 공동근무자, 룰검사 제외 ({evidence})')
    st.caption('8.11은 8번과 11번의 공동근무입니다. 신규 여부는 조별 명단·연차일정의 입사 정보를 함께 확인합니다.')
    st.caption('주간·야간 공통: 근무 포스트·순찰과 휴게가 중복되면 근무·순찰을 우선합니다. 원본의 표기는 그대로 보존합니다.')
    for message in images.rest_priority_notes(rows,mapping):st.info(message)
    with st.expander('휴게 중복을 제외한 실제 배정 확인표',expanded=False):
        st.dataframe(pd.DataFrame(images.apply_rest_priority(rows)),hide_index=True,width='stretch')
    from import_ui import _UPLOAD_GRID,fresh_upload_event
    st.caption('같은 시간의 번호끼리 끌어 교환할 수 있습니다. 인식 누락은 위 입력 표에서 먼저 수정하세요.')
    event=_UPLOAD_GRID(data={'html':images.review_html(rows,mapping),'edit':True,'menus':{}},key=key+'_drag',default=None)
    if fresh_upload_event(event,key+'_drag_nonce') and event.get('kind')=='swap':
        try:
            changed=images.swap_review(rows,event['a'],event['b'])
            st.session_state['schedule_image_draft']=(digest,replace(draft,rows=changed,mapping=mapping,extra_names=extras))
            st.session_state[key+'_revision']=revision+1
            st.rerun()
        except (ValueError,KeyError,IndexError) as exc:st.error(str(exc))
    for row in rows:
        for col,value in row.items():
            if value==images.UNKNOWN:st.warning(f'{row["시간"]} {col}: 확인 필요')
    unresolved=sum(v==images.UNKNOWN for row in rows for v in row.values())
    if unresolved:st.error(f'아직 확인하지 않은 칸 {unresolved}개가 있습니다. 수정 전에는 저장되지 않습니다.')
    mode='FM'
    off=[];statuses={}
    if kind=='night':
        mode=st.radio('원본 실제 운영 모드',['FM','유도리'],horizontal=True,key=key+'_mode')
        off=st.multiselect('원본에서 전 시간 근무불가인 사람',list(mapping),format_func=lambda p:f'{p} {mapping[p]}',key=key+'_off')
    else:
        with st.expander('출근 상태 확인 (반차·연차·기타가 있으면 변경)',expanded=False):
            for p,n in mapping.items():
                statuses[p]=st.selectbox(f'{p}번 {n} 상태',['출근','오전반차','오후반차','연차','기타'],key=key+'_status_'+p)
    if not day or team=='확인 필요' or unresolved:
        st.caption('날짜·근무조·확인 필요 칸을 모두 확인하면 저장할 수 있습니다.');return
    draft=replace(draft,kind=kind,extra_names=extras)
    try:
        if kind=='night':
            from night_shift.models import Mode,HistoryInput
            from night_shift.validator import validate_first_trial
            from night_shift.schedule_edit import explain_errors
            from night_shift.service import calculate_all_stats
            schedule=images.build_night(day,rows,mapping,Mode.FM if mode=='FM' else Mode.FLEXIBLE,off,newcomers)
            errors=validate_first_trial(schedule,HistoryInput((),()),rules_v220=True)
            messages=explain_errors(errors,schedule.context)
            st.dataframe(pd.DataFrame([{'직원':s.name,'실근무':s.actual_work_time_value,'실휴게':s.actual_rest_time_value,'피로도':s.fatigue_value} for s in calculate_all_stats(schedule).values()]),hide_index=True,width='stretch')
            target=store_dir()
        else:
            schedule=images.build_day(day,rows,mapping,kind,statuses,newcomers)
            if kind=='day':
                from night_shift.day_shift import validate_day
                messages=[str(e) for e in validate_day(schedule)];target=day_store_dir()
            else:
                from night_shift.weekend_day import validate
                messages=validate(schedule);target=store_dir()/'weekend_day'
    except (ValueError,KeyError) as exc:
        st.error(f'저장 전 확인: {exc}');return
    if kind in ('night', 'weekend_day'):
        from night_shift.fatigue_ledger_ui import render as render_ledger
        render_ledger(target, day, 'night' if kind == 'night' else 'weekend', schedule, key=key)
    if messages:
        st.warning('현재 규칙과 다른 부분이 있습니다. 실제 수행한 원본 기록이라면 경고를 함께 남기고 저장할 수 있습니다.')
        with st.expander('규칙 검사 결과',expanded=False):
            for message in messages:st.caption(str(message))
    else:st.success('당일 규칙 검사 통과 (이전 회차 이력 검사는 제외)')
    current=images.fingerprint(target,day);snap=key+'_snapshot_'+str(target)+'_'+str(day)
    expected=st.session_state[snap]
    if expected!=current:st.error('확인 중 저장본이 바뀌었습니다. 파일을 다시 분석하세요.');return
    if current:st.info(f'{day} 시간별 포스트 투입자가 같으면 유지하고(휴게·대기 차이 제외), 다르면 백업 후 교체하며 비고에 표시합니다.')
    verified=st.checkbox('원본의 날짜·근무조·이름·모든 시간 배정을 대조했고 실제 기록으로 저장합니다.',key=key+'_verified')
    if st.button(f'💾 {day} {LABELS[kind]} 이미지 확인본 저장',type='primary',disabled=not verified,key=key+'_save'):
        try:
            if kind=='night':
                from night_shift.history_import import save_import
                extra={'source_bytes':data,'source_file':file.name,'source_hash':draft.source_hash,'final_save_method':'upload',
                       'source_review':{'kind':kind,'team':team,'mapping':mapping,'extra_names':extras,'rows':rows,
                                        'applied_rows':images.apply_rest_priority(rows),'newcomers':newcomers,'newcomer_evidence':newcomer_info,
                                        'rest_priority_notes':images.rest_priority_notes(rows,{**mapping,**extras})}}
                from night_shift.import_compare import identical
                from night_shift.history_store import record_to_json
                save_import(target,schedule,'image-import','이미지 원본 대조 확인.\n'+'\n'.join(messages),expected,extra)
            else:
                images.save_day_image(target,schedule,draft,rows,mapping,data,file.name,expected,team,statuses)
            from night_shift.cp_schedule import save_image_override
            cp_changed = team == 'A' and save_image_override(
                store_dir(), day, 'night' if kind == 'night' else 'day', rows, extras, file.name)
            from night_shift.source_attachment import stash
            stash(target,data,file.name)
            from history_ui import store_dir as _store
            from night_shift.kakao_sync import purge_overwrite_copies   # 이전 사본은 남기지 않음 (2026-10-11)
            purge_overwrite_copies(_store())
            after=images.fingerprint(target,day)
            st.session_state['import_saved_message']=f'{day} {LABELS[kind]} 포스트 투입자·시간이 같아 기존 기록을 유지했습니다.' if after==expected else f'{day} {LABELS[kind]} 확인본을 저장했습니다.'+(' 이전 근무표는 Windows 휴지통으로 보내고 비고에 덮어씌워진 근무표로 표시했습니다.' if expected else '')
            if cp_changed:st.session_state['import_saved_message'] += ' CP 시간표 변경을 별도로 반영했습니다.'
            st.session_state[snap]=images.fingerprint(target,day)
            st.rerun()
        except (ValueError,OSError) as exc:st.error(f'저장하지 못했습니다: {exc}')

def render_saved_image(data):
    """Originals stay on disk; the program table is the sole visible schedule."""
    return
