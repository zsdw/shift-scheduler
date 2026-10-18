import unittest
import tempfile
from pathlib import Path
from datetime import date
from night_shift.cp_schedule import save_image_override, hourly

class CPImageOverrideTests(unittest.TestCase):
    def test_half_night_pattern_and_blank_shuttle_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder); day=date(2026,10,16)
            values=['CP1.CP3','CP1.CP2','CP2.CP3']*2+['CP1.CP3','CP1.CP2','CP2','CP1','CP2','CP1','CP2','CP1']
            rows=[{'時間': '', '시간':f'{(18+t)%24:02}:00','CP':v,'셔틀':''} for t,v in enumerate(values)]
            security=store/'2026-10-16.json';security.write_text('original')
            self.assertTrue(save_image_override(store,day,'night',rows,{'CP1':'덕영','CP2':'철룡','CP3':'혁준'},'image.png'))
            self.assertEqual(hourly(store,day,'night',{'1':'덕영','2':'철룡','3':'혁준'}),{'hours':values,'shuttle':''})
            self.assertFalse(save_image_override(store,day,'night',rows,{'CP1':'덕영','CP2':'철룡','CP3':'혁준'},'image.png'))
            self.assertEqual(security.read_text(),'original')
            self.assertNotEqual(hourly(store,date(2026,10,17),'night',{'1':'덕영','2':'철룡','3':'혁준'})['hours'],values)
