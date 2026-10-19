"""PC·폰 업로드 파일 확인과 최종 실제 근무표 저장."""
from datetime import date
from dataclasses import replace
from hashlib import sha256
from html import escape
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from night_shift import history_import as importer
from night_shift.models import Mode,HistoryInput
from night_shift.service import calculate_all_stats
from night_shift.validator import validate_first_trial
from night_shift.schedule_edit import explain_errors
from history_ui import store_dir

_UPLOAD_GRID=components.declare_component('upload_sheet',path=str(Path(__file__).resolve().parent/'night_shift/day_grid'))
_UPLOAD_NIGHT=components.declare_component('upload_night',path=str(Path(__file__).resolve().parent/'night_shift/drag_grid'))


def fresh_upload_event(event,key):
    if not isinstance(event,dict) or not event.get('nonce') or st.session_state.get(key)==event['nonce']:
        return False
    st.session_state[key]=event['nonce']
    return True


def upload_field_html(grid,mapping):
    """인식 직후의 확인표도 포스트별 번호를 직접 끌어서 교환한다."""
    columns=[c for c in importer.CHOICES if c!='근무불가']
    parts=['<style>.dsheet{border-collapse:collapse;min-width:760px;width:100%;text-align:center;background:white;color:#111827;font-size:12px}.dsheet td,.dsheet th{border:1px solid #94a3b8;height:34px}.dsheet span{display:inline-block;padding:7px;background:#f1f5f9;border-radius:4px}</style><div style="overflow-x:auto"><table class="dsheet"><tr><th>시간</th>']
    parts += [f'<th>{escape(c)}</th>' for c in columns]
    parts.append('</tr>')
    for t in range(14):
        parts.append(f'<tr><th>{(18+t)%24:02d}시</th>')
        for col in columns:
            parts.append('<td>')
            for token,row in grid.items():
                if row[t]==col:
                    parts.append(f'<span data-who="{escape(token)}" data-t="{t}" title="{escape(mapping[token])}">{escape(token)}</span> ')
            parts.append('</td>')
        parts.append('</tr>')
    parts.append('</table></div>')
    return ''.join(parts)


def render_bulk_review(plans,key):
    """일괄 파일도 저장 전 각 날짜의 확인표를 상시 교환 가능하게 표시한다."""
    ready=[p for p in plans if p.record is not None and p.status=='new']   # 바로 저장할 새 날짜만
    if not ready:return
    index=st.selectbox('확인·교환할 업로드 근무표',range(len(ready)),
                       format_func=lambda i:f'{ready[i].day} {"야간" if ready[i].shift=="night" else "주간"}',key='bulk_review_day')
    item=ready[index]
    st.caption('✋ 번호를 꾹 누른 채 같은 시간의 다른 번호로 끌어놓으세요. 교환한 내용으로 최종 저장됩니다.')
    if item.shift=='day':
        from day_ui import day_sheet_html
        from night_shift.day_shift import edit_day
        event=_UPLOAD_GRID(data={'html':day_sheet_html(item.record),'edit':True,'menus':{}},key=f'bulk_day_{key}_{index}',default=None)
        if fresh_upload_event(event,'bulk_review_nonce') and event.get('kind')=='swap':
            try:item.record=edit_day(item.record,event)
            except ValueError as exc:st.error(str(exc));return
            item.note+='\n업로드 확인표에서 근무 교환 반영.'
            st.rerun()
    else:
        from night_shift.schedule_edit import record_grid_payload
        from night_shift.actual_edit import apply_edits
        event=_UPLOAD_NIGHT(data=record_grid_payload(item.record),key=f'bulk_night_{key}_{index}',default=None)
        if fresh_upload_event(event,'bulk_review_nonce') and event.get('kind')=='cell':
            a,b=event['source'],event['target']
            if int(a[1])!=int(b[1]):st.error('같은 시간의 번호끼리만 교환할 수 있습니다.');return
            try:item.record=apply_edits(item.record,[{'type':'swap','a':a,'b':b}])
            except ValueError as exc:st.error(str(exc));return
            item.note+='\n업로드 확인표에서 근무 교환 반영.'
            st.rerun()

def render_leave_text(file):
    """연차일정 텍스트 → 날짜를 고르면 상태 기본값 (night_shift.leave_schedule)."""
    from night_shift import leave_schedule
    for encoding in ('utf-8-sig','cp949','utf-16'):
        try:
            text=file.getvalue().decode(encoding); break
        except UnicodeError: continue
    else:
        st.error('연차일정 인코딩을 읽지 못했습니다.'); return
    entries=leave_schedule.parse(text)
    year=st.number_input('연도',2024,2035,2026,key='leave_year')
    if year!=2026:entries=leave_schedule.parse(text,int(year))
    count=sum(len(v) for v in entries.values())
    st.caption(f'{len(entries)}일·{count}줄을 읽었습니다. 명단 이름(이성호→성호처럼 이름 뒤 두 글자)과 통제A(박인철·백원석)만 쓰고, '
               '다른 조 줄은 무시합니다. 교육·예비군·휴가 등은 "기타"(그날 근무 제외 + 비고)로 들어갑니다.')
    st.caption('업로드 일정이 최종 기준입니다. 기존 직접 등록·출근 정정은 백업 후 초기화합니다.')
    if st.button('연차일정 저장 (기존 일정 교체)',type='primary',key='leave_save'):
        try:
            leave_schedule.replace_uploaded_text(store_dir(),text)
        except ValueError as exc:
            st.error(str(exc)); return
        st.session_state.pop('night_status_date',None);st.session_state.pop('day_status_dates',None)
        st.session_state['import_saved_message']='연차일정을 업로드 내용으로 교체했습니다. 기존 직접 등록·출근 정정은 백업 후 초기화했습니다.'
        st.rerun()

def render_bulk(data,file_name):
    """편성표 엑셀 일괄 가져오기: A조·시작일 이후 날짜를 덮어쓰고, 저장본과 같은 날짜는 건너뜀."""
    from night_shift import bulk_import, leave_schedule
    from night_shift.calendar_info import is_off_day
    from night_shift.day_shift import load_roster
    from history_ui import day_store_dir
    from night_shift import order_source
    try:
        reference_key=(sha256(data).hexdigest(),file_name)
        if st.session_state.get('upload_reference_key')!=reference_key:
            st.session_state['upload_references']=order_source.parse_uploaded(data,file_name)
            st.session_state['upload_reference_key']=reference_key
        references=st.session_state['upload_references']
    except (ValueError,OSError) as exc:st.error(f'전체 참조 자료를 읽지 못했습니다: {exc}');return
    st.caption(f'전체 {len(references)}일의 모든 조 자료를 일보·명령서 참조용으로 교체합니다. 실제 근무표는 A조만 저장합니다.')
    start=st.date_input('이 날짜부터 가져오기',date(2026,9,1),key='bulk_start')
    roster=load_roster(store_dir()/'day_roster.json')
    entries=leave_schedule.load(store_dir())
    force=True
    key=('bulk_plan','post-policy-barrier-single-20261010',sha256(data).hexdigest(),file_name,str(start),force)
    from night_shift import upload_review
    if st.session_state.get('bulk_plan_key')!=key:
        with st.spinner('편성표를 읽는 중입니다…'):
            plans=bulk_import.plan(data,store_dir(),day_store_dir(),file_name=file_name,day_roster=roster,start=start,
                                   is_off_day=is_off_day,day_defaults=_DayDefaults(entries,roster),force=force)
            plans=upload_review.triage(store_dir(),plans)   # 새 날짜만 바로 저장, 나머지는 확인 필요 (2026-10-11)
        st.session_state['bulk_plan_key']=key;st.session_state['bulk_plans']=plans
    plans=st.session_state['bulk_plans']
    label={'new':'새로 저장','review':'확인 필요','same':'같음·처리한 원본(그대로)','skip':'건너뜀'}
    shown=[p for p in plans if p.status!='same']
    if shown:
        st.dataframe(pd.DataFrame([{'날짜':p.day.isoformat(),'근무':'야간' if p.shift=='night' else '주간',
                                    '처리':label.get(p.status,p.status),'내용':p.reason} for p in shown]),
                     hide_index=True,width='stretch')
    st.caption(f"그대로 두는 날짜 {sum(p.status=='same' for p in plans)}일(내용이 같거나 이미 처리한 원본).")
    todo=[p for p in plans if p.status=='new']
    render_bulk_review(plans,sha256(repr(key).encode()).hexdigest()[:12])
    st.caption('A조 시트만 근무표로 저장합니다. 저장본이 없는 새 날짜만 바로 저장하고, 이미 저장된 날짜가 바뀌거나 '
               '원본 오기·연차 충돌이면 아래 "확인 필요"에서 반영/기존 유지를 고릅니다. 한 번 처리한 원본은 다음 파일에서 다시 묻지 않습니다.')
    if st.button(f'💾 전체 조 자료 갱신 · 새 날짜 {len(todo)}일 저장',type='primary',key='bulk_apply'):
        saved=bulk_import.apply(todo,store_dir(),day_store_dir())
        referenced=order_source.publish_uploaded(store_dir(),data,file_name,references)
        waiting=upload_review.save_pending(store_dir(),plans,sha256(data).hexdigest(),file_name)
        upload_review.purge_overwrite_copies(store_dir())
        st.session_state.pop('bulk_plan_key',None)
        st.session_state['import_saved_message']=(f'{referenced}일의 전체 조 참조 자료 갱신 · 새 날짜 {saved}일 저장'
                                                  +(f' · 확인 필요 {waiting}건' if waiting else '')+'.')
        st.rerun()


def render_pending():
    """확인 필요 목록 (업로드·카톡 자동 반영 공통, PC·폰): 날짜마다 반영/기존 유지를 고르고 한 번에 처리."""
    from night_shift import upload_review
    info=upload_review.pending(store_dir())
    items=info.get('items',[])
    if not items:return
    st.markdown(f"**⚠️ 확인 필요 {len(items)}건** · {info.get('file','')}")
    st.caption('이미 저장된 근무표와 다르거나 원본 오기·연차 충돌이 있는 날짜입니다. 고르지 않은 날짜는 기존 저장본 그대로 둡니다.')
    decisions={}
    for item in items:
        key=f"{item['day']}|{item['shift']}"
        with st.container(border=True):
            st.markdown(f"**{item['day'][5:].replace('-','/')} {upload_review.SHIFT[item['shift']]}** · {item['reason']}")
            options=['반영','기존 유지'] if item.get('can_apply',True) else ['기존 유지']
            choice=st.radio('처리',['보류',*options],horizontal=True,key=f'pending_{key}',label_visibility='collapsed')
            decisions[key]={'반영':'apply','기존 유지':'keep'}.get(choice)
    count=sum(bool(v) for v in decisions.values())
    if st.button(f'선택한 {count}건 처리',type='primary',disabled=not count,key='pending_apply'):
        try:
            with st.spinner('처리 중입니다…'):
                applied,kept=upload_review.resolve(store_dir(),decisions)
        except (ValueError,OSError) as exc:st.error(str(exc))
        else:
            st.session_state['import_saved_message']=f'반영 {applied}건 · 기존 유지 {kept}건(이 원본은 다음 파일에서 다시 묻지 않음).'
            st.rerun()

class _DayDefaults(dict):
    """날짜 → 주간 연차일정 기본 상태 (bulk_import.day_schedule에서 빠진 사람 상태로 씀)."""
    def __init__(self,entries,roster):super().__init__();self.entries=entries;self.roster=roster
    def get(self,day,default=None):
        from night_shift import leave_schedule
        return leave_schedule.defaults_for(self.entries,day,'day',self.roster)[0]

def render_importer():
    """업로드 칸. 반환값 = 업로드 옆 '현장 양식 다운로드' 자리 (2026-10-05 사용자 요청: 다운로드를 upload 옆으로).
    표가 정해진 뒤 app이 이 자리에 지금 날짜 근무표의 다운로드 버튼을 채운다."""
    # 2026-10-13 사용자 요청: 기본은 접힘. 단 '확인 필요' 건이 있으면 놓치지 않게 펼치고 제목에 건수 표시.
    from night_shift import upload_review
    waiting = len(upload_review.pending(store_dir()).get('items', []))
    title = '📥 파일 업로드 · 현장 양식 다운로드 · 최종 실제 근무표 저장' + (f' · ⚠️ 확인 필요 {waiting}건' if waiting else '')
    with st.expander(title, expanded=bool(waiting)):
        st.caption('주간·야간 근무표 이미지(제목·시간대로 자동 구분), 야간 단일 엑셀, 날짜별 편성표 엑셀 전체(일괄), CP 월간 근무표(엑셀), 연차일정 텍스트를 가져옵니다. '
                   '아래 특이사항은 자동 반영하지 않습니다.')
        upload_col, download_col = st.columns([3, 1], vertical_alignment="center")
        slot = download_col.container()
        slot.caption('🖼 현장 양식: 지금 날짜의 근무표(저장본 또는 고른 생성 후보)를 내려받습니다.')
        with upload_col:
            file=st.file_uploader('근무표·연차일정 파일',type=['xlsx','xlsm','png','jpg','jpeg','txt'],key='history_upload')
        _render_import_body(file)
        render_pending()                                   # 확인 필요 목록 (업로드·카톡 공통, 2026-10-11)
    return slot


def render_cp(data,file_name='CP근무표.xlsx',message_key='import_saved_message'):
    """CP 월간 근무표 엑셀 → 날짜별 주간·야간 CP1~3 확인 → 저장 (같은 날짜는 덮어씀). PC·폰 공통."""
    from night_shift import cp_schedule
    year=st.number_input('연도',2024,2035,date.today().year,key='cp_year')
    try:entries=cp_schedule.parse_excel(data,int(year))
    except ValueError as exc:st.error(str(exc));return
    rows=[{'날짜':k,**{f'{"주간" if s=="day" else "야간"} CP{n}':v[s].get(n,'') for s in ('day','night') for n in '123'}}
          for k,v in sorted(entries.items())]
    st.success(f'CP 근무표 {len(entries)}일을 읽었습니다. 원본과 맞는지 확인하고 저장하세요.')
    st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    if st.button('💾 CP 근무표 저장',type='primary',key='cp_save',width='stretch'):
        cp_schedule.save_uploaded(store_dir(),data,file_name,int(year))
        st.session_state[message_key]=f'CP 근무표 {len(entries)}일 저장 — 해당 월의 이전 배정을 교체하고 날짜별 근무표·명령서에 자동 반영합니다.'
        st.rerun()


def _render_import_body(file):
        if file is None:return
        data=file.getvalue();image=file.name.lower().endswith(('.png','.jpg','.jpeg'))
        if len(data)>20*1024*1024:st.error('20MB 이하 파일을 올려주세요.');return
        if file.name.lower().endswith('.txt'):
            render_leave_text(file);return
        if image:
            from image_import_ui import render_image_review
            digest=sha256(data).hexdigest()
            reanalyze=st.button('파일 다시 분석',key='import_analyze')
            render_image_review(file,data,digest,reanalyze)
            return
        if not image:
            try:sheets=importer.excel_sheets(data)
            except Exception as exc:st.error(f'파일을 읽을 수 없습니다: {exc}');return
            from night_shift import bulk_import
            if any(bulk_import.SHEET.search(s) for s in sheets):
                render_bulk(data,file.name);return
            from night_shift import cp_schedule
            if cp_schedule.is_cp_workbook(data):                            # CP 월간 근무표 (2026-10-05)
                render_cp(data,file.name);return
        try:
            sheet=st.selectbox('가져올 시트',importer.excel_sheets(data),key='import_sheet') if not image else '이미지'
        except Exception as exc:st.error(f'파일을 읽을 수 없습니다: {exc}');return
        digest=sha256(data+sheet.encode()).hexdigest()
        reanalyze=st.button('파일 다시 분석',key='import_analyze')
        saved=st.session_state.get('history_import_draft')
        if reanalyze or not saved or saved[0]!=digest:
            try:
                with st.spinner('근무표를 읽는 중입니다…'):
                    draft=importer.parse_image(data) if image else importer.parse_excel(data,sheet)
                st.session_state['history_import_draft']=(digest,draft)
                for key in list(st.session_state):
                    if key.startswith('import_'+digest[:12]+'_snapshot_'):del st.session_state[key]
            except Exception as exc:st.error(f'분석하지 못했습니다: {exc}')
        saved=st.session_state.get('history_import_draft')
        if not saved or saved[0]!=digest:return
        draft=saved[1];prefix='import_'+digest[:12]
        if image:st.image(data,caption='업로드 원본',width='stretch')
        day=st.date_input('기록할 날짜 (18시 시작 기준)',draft.day or date.today(),key=prefix+'_date')
        if draft.day is None:st.warning('날짜를 읽지 못했습니다. 원본 날짜를 직접 골라주세요.')
        mode_name=st.radio('실제로 운영한 모드',['FM','유도리'],horizontal=True,key=prefix+'_mode')
        mode=Mode.FM if mode_name=='FM' else Mode.FLEXIBLE
        with st.expander('원본 인식 결과·확인할 내용',expanded=bool(draft.warnings)):
            for warning in draft.warnings:st.warning(warning)
            st.dataframe(pd.DataFrame(draft.raw),hide_index=True,width='stretch')
        st.write('**번호별 실제 직원 확인**')
        mapping={}
        known=list(importer.ROSTER.values())
        for token in importer.ROSTER:
            value=draft.mapping.get(token,importer.ROSTER[token])
            if value not in known:
                st.warning(f'{token}번에서 읽은 이름 {value!r}을 실제 직원과 연결하세요.')
                value=importer.ROSTER[token]
            mapping[token]=st.selectbox(f'{token}번 직원',known,index=known.index(value),key=prefix+'_who_'+token)
        rows=[{'시간':f'{(18+t)%24:02}시',**{e:draft.grid[e][t] for e in importer.ROSTER}} for t in range(14)]
        revision=st.session_state.get(prefix+'_grid_revision',0)
        with st.expander('칸 배정 직접 입력·인식 오류 수정',expanded=any('확인 필요' in row for row in draft.grid.values())):
            edited=st.data_editor(pd.DataFrame(rows),hide_index=True,width='stretch',disabled=['시간'],
                key=prefix+'_grid_'+str(revision),column_config={e:st.column_config.SelectboxColumn(
                    f'{e} {mapping[e]}',options=importer.CHOICES,required=True) for e in importer.ROSTER})
        grid={e:list(edited[e]) for e in importer.ROSTER}
        st.caption('✋ 번호를 꾹 누른 채 같은 시간의 다른 번호로 끌어놓으세요. 교환한 내용으로 최종 저장됩니다.')
        event=_UPLOAD_GRID(data={'html':upload_field_html(grid,mapping),'edit':True,'menus':{}},key=prefix+'_drag',default=None)
        if fresh_upload_event(event,prefix+'_drag_nonce') and event.get('kind')=='swap':
            try:
                (a,t),(b,u)=event['a'],event['b'];t=int(t);u=int(u)
                if a not in grid or b not in grid or not 0<=t<14 or t!=u:
                    raise ValueError('같은 시간의 번호끼리만 교환할 수 있습니다.')
                if grid[a][t]=='근무불가' or grid[b][t]=='근무불가':raise ValueError('근무불가 번호는 교환할 수 없습니다.')
                grid[a][t],grid[b][t]=grid[b][t],grid[a][t]
                st.session_state['history_import_draft']=(digest,replace(draft,grid=grid))
                st.session_state[prefix+'_grid_revision']=revision+1
                st.rerun()
            except (ValueError,KeyError,IndexError) as exc:st.error(str(exc))
        st.caption('표에 없는 사람은 휴게입니다. 중복 칸은 실제 배정을 선택하세요. 결근·미출근 시간은 근무불가로 바꾸세요.')
        from night_shift.models import BARRIER_SINGLE_FROM
        if day >= BARRIER_SINGLE_FROM:
            installer_post = 'G2' if any(g[2]=='G2' for g in grid.values()) else 'I1'
            installs=[(token,2) for token,g in grid.items() if g[2]==installer_post]
            removes=[(token,10) for token,g in grid.items() if g[10]=='I1']
            install=', '.join(mapping[token] for token,_ in installs) or '확인 안 됨'
            remove=', '.join(mapping[token] for token,_ in removes) or '확인 안 됨'
            st.caption(f'차단봉: 20시 {installer_post} 단독({install}), 04시 I1 단독({remove}). 대기자는 참여하지 않습니다.')
        else:
            options=['확인 안 됨','업무 없었음',*importer.ROSTER]
            install=st.selectbox('20시 실제 차단봉 설치 담당',options,key=prefix+'_install')
            remove=st.selectbox('04시 실제 차단봉 철수 담당',options,key=prefix+'_remove')
            installs=[];removes=[]
            if install in importer.ROSTER:installs.append((install,2))
            if remove in importer.ROSTER:removes.append((remove,10))
            if mode==Mode.FLEXIBLE and install in importer.ROSTER:
                installs.extend((e,2) for e in importer.ROSTER if edited.iloc[2][e]=='I1')
            if install=='확인 안 됨' or remove=='확인 안 됨':
                st.warning('차단봉 담당 미확인 이력은 차단봉 회차 제한을 완전히 계산할 수 없습니다. 확인된 담당자만 기록합니다.')
        names_to_id={v:k for k,v in importer.ROSTER.items()}
        identities={token:names_to_id[name] for token,name in mapping.items()}
        # 업로드 근무표 원본은 기존 연차일정으로 배정을 바꾸지 않는다.
        try:
            record=importer.build_import_record(day,mode,grid,identities,importer.ROSTER,installs,removes)
            from night_shift.fatigue_ledger_ui import render as render_ledger
            render_ledger(store_dir(), day, current=record, key=prefix)
            stats=calculate_all_stats(record)
        except Exception as exc:st.error(f'저장 전 수정이 필요합니다: {exc}');return
        st.dataframe(pd.DataFrame([{'직원':v.name,'피로도':v.fatigue_value,'실근무':v.actual_work_time_value,
            '실휴게':v.actual_rest_time_value,'순찰':v.patrol_count} for v in stats.values()]),hide_index=True,width='stretch')
        errors=validate_first_trial(record,HistoryInput((),()),rules_v220=True)
        if errors:
            st.warning('현재 룰북 기준과 다른 기록입니다. 실제 수행한 내용이라면 경고와 함께 저장할 수 있습니다.')
            for message in explain_errors(errors,record.context):st.caption(message)
        else:st.success('당일 하드룰 검증 통과 (이전 회차 이력 검사는 제외)')
        expected=importer.fingerprint(store_dir(),day)
        snapshot_key=prefix+'_snapshot_'+str(day)
        if snapshot_key not in st.session_state:st.session_state[snapshot_key]=expected
        original=st.session_state[snapshot_key]
        if original!=expected:st.error('분석 후 기존 이력이 변경됐습니다. 새로고침하고 파일을 다시 분석하세요.');return
        if expected is not None:
            st.caption(f'{day} 시간별 포스트 투입자가 같으면 유지합니다(휴게·대기 차이 제외). 다르면 백업 후 교체하고 비고에 덮어씌워진 근무표로 표시합니다.')
        verified=st.checkbox('날짜·모드·번호별 직원·배정·차단봉 내용을 원본과 대조했고, 실제 이력으로 기록합니다.',key=prefix+'_verified')
        note=st.text_input('기록 메모',key=prefix+'_note')
        if not verified:st.caption('위 원본 대조 확인을 체크하면 최종 저장 버튼이 켜집니다.')
        if st.button(f'💾 {day} 업로드 파일을 최종 실제 근무표로 저장',type='primary',disabled=not verified,key=prefix+'_save'):
            try:
                provenance=(f'가져온 파일: {file.name} / {sheet}\n'+note+
                    f'\n차단봉 설치: {install}, 철수: {remove}\n아래 특이사항은 제외. 사용자 원본 대조 확인.\n'+
                    '\n'.join(explain_errors(errors,record.context)))
                importer.save_import(store_dir(),record,'image-import' if image else 'excel-import',provenance,original,
                                     {'source_file':file.name,'source_sheet':sheet,'final_save_method':'upload','source_bytes':data})
                from night_shift.source_attachment import stash
                stash(store_dir(),data,file.name)
                from night_shift.kakao_sync import purge_overwrite_copies   # 이전 사본은 남기지 않음 (2026-10-11)
                purge_overwrite_copies(store_dir())
                st.session_state.pop('history_import_draft',None)
                st.session_state['import_saved_message']=f'{day} 포스트 투입자·시간이 같아 기존 기록을 유지했습니다.' if importer.fingerprint(store_dir(),day)==original else f'{day} 업로드 확인본을 저장했습니다.'+(' 이전 근무표는 Windows 휴지통으로 보냈고 비고에 덮어씌워진 근무표로 표시했습니다.' if original else '')
                st.rerun()
            except Exception as exc:st.error(f'저장하지 못했습니다: {exc}')
