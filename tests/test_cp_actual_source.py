import json,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from night_shift import cp_schedule as cp,order_source

DAY=date(2026,10,10)
class CpActualSourceTests(unittest.TestCase):
    def test_latest_roster_excludes_stale_third_person(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            cp.save(store,{str(DAY):{'night':{'1':'권혁준','2':'이덕영','3':'안철룡'},'day':{}}})
            path=store/'order_source'/'uploaded_sources.json';path.parent.mkdir()
            path.write_text(json.dumps({'sources':{str(DAY):{'night':{'cp':{'1':'혁준','2':'덕영'}}}}}),encoding='utf-8')
            self.assertEqual(cp.for_day(store,DAY,'night'),{'1':'권혁준','2':'이덕영'})
            source=order_source.cp_sources({'night':{'cp':{'3':'철룡'},'cells':{'7':{'CP':'CP2.CP3','셔틀':'CP3'}}}},store,DAY)
            self.assertNotIn('3',source['night']['cp'])
            self.assertEqual(source['night']['cells']['7']['셔틀'],'')

    def test_new_cp_upload_and_manual_leave(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder)
            from tests.test_cp_schedule import workbook
            cp.save_uploaded(store,workbook(),'cp.xlsx',2026)
            day=date(2026,10,3)
            with patch('night_shift.daily_report.entries_for',return_value=[{'name':'안철룡','kind':'연차','manual':True,'presence':'자동'}]):
                self.assertEqual(cp.for_day(store,day,'night'),{'1':'권혁준','2':'이덕영'})
            with patch('night_shift.daily_report.entries_for',return_value=[{'name':'안철룡','kind':'연차','manual':True,'presence':'출근'}]):
                self.assertIn('3',cp.for_day(store,day,'night'))

if __name__=='__main__':unittest.main()
