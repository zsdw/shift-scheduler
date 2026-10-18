import io,json,os,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import openpyxl
from night_shift import order_source as source
from night_shift.source_attachment import stash,original

def book(team='B',value='1',days=(('26년01월01일(주)','B'),('26년10월11일(야)','C'))):
    w=openpyxl.Workbook();w.remove(w.active)
    for title,group in days:
        s=w.create_sheet(title);s['A3']='근무조 : '+group+'조';s['F5']='1경빈' if group=='B' else '1승회'
        s['A7']='근무시간';s['F7']='G1';s['A8']='08:00' if '(주)' in title else '18:00';s['F8']=value
    out=io.BytesIO();w.save(out);w.close();return out.getvalue()

class LatestUploadReferenceTests(unittest.TestCase):
    def test_all_dates_teams_replace_and_no_old_folder_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);data=book()
            oldcache=store/'order_source'/'2026-10-11.json';oldcache.parent.mkdir();oldcache.write_text('{}')
            source.publish_uploaded(store,data,'old.xlsx')
            self.assertFalse(oldcache.exists())
            self.assertEqual(source.reference_sources(store,date(2026,1,1))['day']['team'],'B')
            self.assertEqual(source.sources_for(store,date(2026,10,11))['night']['team'],'C')
            self.assertFalse(list(store.glob('????-??-??.json')))
            old=list((store/'source_files').glob('*.xlsx'))[0]
            source.publish_uploaded(store,book(value='2',days=(('26년10월11일(야)','C'),)),'new.xlsx')
            self.assertFalse(old.exists())
            with patch.object(source,'latest_file',side_effect=AssertionError('old folder fallback')):
                self.assertEqual(source.reference_sources(store,date(2026,1,1)),{})
                self.assertEqual(source.reference_sources(store,date(2026,10,11))['night']['cells']['18']['G1'],'2')
            self.assertEqual(len(list((store/'source_files').iterdir())),1)
            snapshot=(store/'order_source'/source.UPLOAD_REFERENCE).read_bytes()
            with self.assertRaises(Exception):source.publish_uploaded(store,b'invalid','bad.xlsx')
            self.assertEqual((store/'order_source'/source.UPLOAD_REFERENCE).read_bytes(),snapshot)

    def test_latest_original_global_keeps_reference_and_records(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);source.publish_uploaded(store,book(),'all.xlsx')
            for relative in ('day/source_images/old.png','day/source_files/old.xlsx','source_images/old.jpg'):
                p=store/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'old')
            record=store/'2026-10-10.json';record.write_text('record')
            latest=Path(stash(store/'day',b'new','latest.png'))
            kept=[p for p in store.rglob('*') if p.is_file() and p.parent.name in ('source_files','source_images')]
            self.assertEqual(kept,[latest]);self.assertEqual(record.read_text(),'record')
            self.assertEqual(source.reference_sources(store,date(2026,1,1))['day']['team'],'B')
            self.assertIsNone(original({'source_attachment':str(store/'source_files'/'deleted.xlsx')}))

    def test_reference_only_save_button_pc_mobile_without_a_changes(self):
        from streamlit.testing.v1 import AppTest
        for mobile in (False,True):
            with self.subTest(mobile=mobile),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}),patch('mobile_ui.is_mobile',return_value=mobile),patch('night_shift.bulk_import.plan',return_value=[]):
                at=AppTest.from_string('import import_ui\nfrom tests.test_latest_upload_reference import book\nimport_ui.render_bulk(book(),"all.xlsx")',default_timeout=30).run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                b=at.button(key='bulk_apply');self.assertFalse(b.disabled);b.click().run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                self.assertEqual(source.reference_sources(Path(folder),date(2026,10,11))['night']['team'],'C')
                self.assertFalse(list(Path(folder).glob('????-??-??.json')))

if __name__=='__main__':unittest.main()
