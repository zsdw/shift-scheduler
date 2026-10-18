import unittest
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import json
from night_shift.history_store import record_from_json
from night_shift.schedule_image import render_xlsx,field_cells,FORM_COLUMNS
from openpyxl import load_workbook

class NightExcelViewsTests(unittest.TestCase):
    def test_unfrozen_export_has_only_unsplit_selection_and_preserves_cells(self):
        payload=json.loads((Path(__file__).parent/'fixtures/patrol_rules_record.json').read_text(encoding='utf-8'))
        record=record_from_json(payload['plan'])
        data=render_xlsx(record)
        with ZipFile(BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            view=root.find('s:sheetViews/s:sheetView',ns)
            self.assertIsNone(view.find('s:pane',ns))
            selections=view.findall('s:selection',ns)
            self.assertEqual(len(selections),1)
            self.assertNotIn('pane',selections[0].attrib)
            self.assertEqual(selections[0].get('activeCell'),'A1')
        book=load_workbook(BytesIO(data));sheet=book.active
        self.assertIsNone(sheet.freeze_panes)
        expected=field_cells(record)
        for t,row in enumerate(expected['rows']):
            for col,value in zip(FORM_COLUMNS,row):
                stored=sheet[f'{col}{8+t}'].value
                self.assertEqual('' if stored is None else str(stored),value)
        book.close()
