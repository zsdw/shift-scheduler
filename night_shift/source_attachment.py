"""Latest uploaded original only, shared by PC/mobile; prior file copies are discarded."""
import hashlib,mimetypes,json
from pathlib import Path

def root_store(store):
    store=Path(store)
    return store.parent if store.name in ('day','weekend_day','day_images') else store

def prune(store,keep):
    """프로그램의 업로드 보관 폴더만 정리. 실제 이력 JSON·바탕화면 원본은 보존."""
    root=root_store(store).resolve();keep=Path(keep).resolve()
    for base in (root,root/'day',root/'weekend_day',root/'day_images'):
        for folder in (base/'source_files',base/'source_images'):
            if not folder.exists() or not folder.resolve().is_relative_to(root):continue
            for candidate in folder.iterdir():
                resolved=candidate.resolve()
                if candidate.is_file() and resolved.is_relative_to(root) and resolved!=keep and candidate.suffix.lower() in ('.xlsx','.xlsm','.xls','.png','.jpg','.jpeg','.webp','.gif','.txt'):
                    candidate.unlink()
        trash=base/'.trash'
        if trash.exists() and trash.resolve().is_relative_to(root):
            for pattern in ('upload_replace_*_leave_schedule.txt','leave_schedule_*.txt'):
                for candidate in trash.glob(pattern):
                    if candidate.is_file() and candidate.resolve().is_relative_to(root):candidate.unlink()

def stash(store,data,filename):
    suffix=Path(filename or '').suffix.lower()
    if not suffix:  # Uploads without a usable name: infer the format from the file signature.
        signatures={b'PK\x03\x04':'.xlsx',b'\x89PNG':'.png',b'\xff\xd8\xff':'.jpg',b'GIF8':'.gif',b'\xd0\xcf\x11\xe0':'.xls'}
        suffix=next((s for head,s in signatures.items() if data.startswith(head)),'')
    if suffix not in ('.xlsx','.xlsm','.xls','.png','.jpg','.jpeg','.webp','.gif','.txt'):raise ValueError('지원하지 않는 원본 파일 형식입니다.')
    store=root_store(store)
    path=Path(store)/'source_files'/(hashlib.sha256(data).hexdigest()+suffix)
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    prune(store,path)
    (Path(store)/'latest_upload.json').write_text(json.dumps({'file':Path(filename or path.name).name,'path':str(path.resolve())},ensure_ascii=False),encoding='utf-8')
    return str(path.resolve())

def label(data):
    source=str(data.get('source',''))
    if source.startswith('excel'):return '엑셀저장본'
    if source.startswith('image'):return '이미지 저장본'
    return '저장본'

def original(data):
    for key in ('source_attachment','source_image'):
        path=Path(data.get(key) or '')
        if path.is_file():return path
    if data.get('source_attachment') or data.get('source_image'):return None
    name=str(data.get('source_file') or '')
    if name:
        direct=Path(name)
        if direct.is_absolute() and direct.is_file():return direct
        folder=Path.home()/'Desktop'/'업무'
        for base in (folder/'업무자동화'/'업무일지',folder):
            candidate=base/Path(name).name
            if candidate.is_file():return candidate
    return None

def render_button(data,key,where=None):
    """Original-file button, placed beside '💾 실제 근무 저장' (where = that row's column)."""
    import streamlit as st
    where=where or st
    kind=label(data)
    if kind=='저장본':return
    path=original(data)
    if not path:
        where.caption('이전 업로드 원본은 정리됐습니다. 최신 파일만 보관합니다.');return
    mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    name=data.get('source_file') or path.name
    if st.runtime.exists():
        url=st.runtime.get_instance().media_file_mgr.add(path.read_bytes(),mime,coordinates='original-'+key,file_name=Path(name).name)
        where.link_button('엑셀저장본 보기' if kind=='엑셀저장본' else '이미지파일 보기',url)
    else:
        where.download_button('엑셀저장본 보기' if kind=='엑셀저장본' else '이미지파일 보기',path.read_bytes(),file_name=Path(name).name,mime=mime,key='original-'+key)
