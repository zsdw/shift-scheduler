"""현장 양식 이미지 특이사항 칸 (2026-10-05 사용자 확정): 근무표 칸에서 담당 번호를 읽어 자동 표기."""
import unittest
from datetime import date

from night_shift.models import Mode, NightType
from night_shift.schedule_image import field_duty_notes, render_png
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def plan(day, night):
    staff = (StaffInput("A", "통제", True, False, None, True),
             *(StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()))
    result = run_schedule(ShiftRequest(day, night, Mode.FM, staff), HistorySelection(),
                          SolveOptions(rules_version="2.20", seconds=15))
    assert result.valid
    return result.record


def token(record):
    numbers = {a.employee_id: a.display_number for a in record.context.attendance}
    return lambda e: "A" if numbers.get(e) is None else str(numbers[e])


def at(record, slot, label):
    return next(token(record)(r.employee_id) for r in record.assignments
                if r.slot.index == slot and r.displayed_assignment.label == label)


class ArrangeCellsTests(unittest.TestCase):
    def test_a_first_and_second_g2_to_g3(self):
        # 2026-10-06 사용자 확정: G2 '6.A' → G2 A, G3 6 / 같이 적히면 A를 앞에
        from night_shift.schedule_image import arrange_cells
        headers = ['근무시간','G1','L3','I1','G3','G2','G2(1)','G2(2)','CP','셔틀','순찰','보안실','휴 게']
        buckets = [[] for _ in headers]
        buckets[headers.index('G2')] = ['6', 'A']
        buckets[headers.index('휴 게')] = ['3', 'A', '1']
        buckets[headers.index('CP')] = ['CP2', 'CP1']
        arrange_cells(headers, buckets)
        self.assertEqual(buckets[headers.index('G2')], ['A'])
        self.assertEqual(buckets[headers.index('G3')], ['6'])
        self.assertEqual(buckets[headers.index('휴 게')], ['A', '1', '3'])
        self.assertEqual(buckets[headers.index('CP')], ['CP2', 'CP1'])   # CP 칸은 그대로


def fake(cells, absent=()):
    """parasol() 검사용 최소 기록: cells = {(사람, 시간칸): (라벨, 종류)}."""
    from types import SimpleNamespace as N
    ids = ("A", "1", "6")
    employees = [N(employee_id="A", name="통제"), N(employee_id="1", name="만년"), N(employee_id="6", name="준호")]
    attendance = [N(employee_id=e, present=e not in absent, display_number=None if e == "A" else int(e)) for e in ids]
    rows = [N(employee_id=e, slot=N(index=t), displayed_assignment=N(label=label, kind=kind))
            for (e, t), (label, kind) in cells.items()]
    return N(context=N(employees=employees, attendance=attendance), assignments=rows)


class ParasolTests(unittest.TestCase):
    """흡연장 파라솔 (2026-10-11 사용자 확정): 19시 G2 → 없으면 선임 19·20시 휴게/대기면 선임, 둘 다 근무면 A,
    A 연차면 선임."""
    def check(self, cells, absent=()):
        from night_shift.schedule_image import parasol
        record = fake(cells, absent)
        tok = token(record)
        def who(slot, label):
            found = [tok(r.employee_id) for r in record.assignments
                     if r.slot.index == slot and r.displayed_assignment.label == label]
            return ".".join(found) or "-"
        return parasol(record, tok, who)

    def test_rules(self):
        from night_shift.models import AssignmentKind as K
        post, rest, wait = ("G1", K.POST), ("휴게", K.REST), ("보안실", K.SECURITY_STANDBY)
        self.assertEqual(self.check({("1", 1): ("G2", K.POST), ("6", 1): rest, ("1", 2): post}), "1")  # 19시 G2
        self.assertEqual(self.check({("1", 2): ("G2", K.POST), ("6", 1): post, ("6", 2): post}), "A")  # 20시 G2는 안 봄
        self.assertEqual(self.check({("6", 1): post, ("6", 2): rest}), "6")                             # 20시 휴게
        self.assertEqual(self.check({("6", 1): wait, ("6", 2): post}), "6")                             # 19시 대기
        self.assertEqual(self.check({("6", 1): post, ("6", 2): ("순찰", K.PATROL)}), "A")               # 둘 다 근무
        self.assertEqual(self.check({("6", 1): post, ("6", 2): post}, absent=("A",)), "6")              # A 연차


class FieldNotesTests(unittest.TestCase):
    def test_weekday_uses_g2_and_posts(self):
        record = plan(date(2026, 10, 6), NightType.N1)                     # 20시 G2 있음
        left, right = field_duty_notes(record, token(record))
        self.assertTrue(left[0].startswith("흡연장 파라솔 - "))
        self.assertEqual(left[1], f"21시 폐문 및 차단봉 설치 - {at(record, 2, 'G2')}")   # G2 있으면 20시 G2 (2026-10-06)
        self.assertEqual(left[2], f"21시 라이브러리 시건 - {at(record, 3, 'L3')}")
        self.assertEqual(left[3], f"24시 폐문 및 차단봉 설치 - {at(record, 6, 'I1')}")   # 24시(2차 폐문) I1
        self.assertEqual(left[4], f"05시 개문 및 차단봉 공조실 이동 - {at(record, 10, 'I1')}")
        self.assertEqual(right, ["05시 0호기 1층 이동 - A", f"06시 라이브러리 시건 해제 - {at(record, 12, 'L3')}"])
        self.assertTrue(render_png(record))

    def test_weekend_closing_uses_i1(self):
        record = plan(date(2026, 10, 10), NightType.N4)                    # 20시 G2 없음
        left = field_duty_notes(record, token(record))[0]
        self.assertEqual(left[1], f"21시 폐문 및 차단봉 설치 - {at(record, 2, 'I1')}")  # G2 없으면 20시 I1

    def test_zero_elevator_follows_manager_on_duty(self):
        # 2026-10-23 사용자 지적: 05시 0호기 1층 이동은 그 시간 관리자 — A 결근이면 대행 준호, 승계 날은 교대 기준
        from types import SimpleNamespace as N
        from night_shift.schedule_image import manager_at
        def ctx(a_present=True, handover=None, reverse=False):
            attendance = [N(employee_id="A", present=a_present, display_number=None, acts_as_manager=a_present),
                          N(employee_id="6", present=True, display_number=6, acts_as_manager=not a_present)]
            return N(context=N(attendance=attendance, manager_handover=handover, manager_handover_reverse=reverse))
        tok = lambda e: "A" if e == "A" else e
        self.assertEqual(manager_at(ctx(), tok, 11), "A")
        self.assertEqual(manager_at(ctx(a_present=False), tok, 11), "6")
        self.assertEqual(manager_at(ctx(handover=(7, "6")), tok, 11), "6")                # 후반부 반차·긴급 승계: 01시부터 준호
        self.assertEqual(manager_at(ctx(handover=(7, "6"), reverse=True), tok, 11), "A")  # 전반부 반차: 01시부터 A


if __name__ == "__main__":
    unittest.main()
