"""Project a validated service result into the supplied field night-shift layout."""

from collections import defaultdict
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font

from .excel_exporter import _history_sheet, _sorted_people, _summary_sheet, _validation_sheet
from .models import AssignmentKind
from .presentation import PATROL_LABELS
from .service import ServiceResult, rulebook_label


TEMPLATE = Path(__file__).parent / "templates" / "field_night.xlsx"
ROSTER_COLUMNS = ("F", "K", "P", "U", "Z", "AE", "AJ")
POST_COLUMNS = {
    "G1": "F", "L3": "K", "I1": "P", "G3": "U", "G2": "Z",
    "G2(1)": "AE", "G2(2)": "AJ",
}
HEADER_CELLS = {
    "A7": "근무시간", "F7": "G1", "K7": "L3", "P7": "I1",
    "U7": "G3", "Z7": "G2", "AE7": "G2(1)", "AJ7": "G2(2)",
    "AO7": "CP", "AT7": "차단봉", "AY7": "순찰", "BD7": "보안실", "BI7": "휴게",
}


def _token(person) -> str:
    return str(person.display_number) if person.display_number is not None else "A"


def _field_column(assignment) -> str:
    kind = assignment.kind
    if kind == AssignmentKind.POST:
        try:
            return POST_COLUMNS[assignment.label]
        except KeyError as exc:
            raise ValueError(f"현장 양식에 없는 표시 포스트: {assignment.label}") from exc
    if kind == AssignmentKind.PATROL:
        return "AY"
    if kind == AssignmentKind.SECURITY_STANDBY:
        return "BD"
    if kind == AssignmentKind.REST:
        return "BI"
    if kind == AssignmentKind.BARRIER_ONLY:
        return "AT"
    if kind == AssignmentKind.UNAVAILABLE:
        return ""
    raise ValueError(f"현장 양식에 없는 배정 종류: {kind}")


def export_field_xlsx(result: ServiceResult) -> bytes:
    """Preserve the source night sheet's geometry and fill it from ServiceResult."""
    if not result.valid or result.record is None:
        raise ValueError("검증을 통과한 근무표만 현장 양식으로 내보낼 수 있습니다.")

    workbook = load_workbook(TEMPLATE)
    sheet = workbook.active
    people = _sorted_people(result)
    if len(people) > len(ROSTER_COLUMNS):
        raise ValueError("현장 양식의 근무자명 칸이 부족합니다.")
    people_by_id = {person.employee_id: person for person in people}
    day = result.context.shift_start_date
    weekdays = "월화수목금토일"
    sheet["A1"] = "야간 근무 편성표"
    sheet["BD1"] = "결 재"
    sheet["BG1"] = "담 당"
    sheet["BL1"] = "팀 장"
    sheet["A3"] = (f"{day:%Y년 %m월 %d일} {weekdays[day.weekday()]}요일 야간근무"
                   f"  ·  {result.context.night_type.value} / {result.context.effective_mode.value}"
                   f"  ·  {rulebook_label(result.rules_version)}  ·  검증 통과 0건")
    sheet["A5"] = "근무자명"
    sheet["F6"] = "A 출근" if any(p.employee_id == "A" for p in people) else "준호 대행"
    sheet["K6"] = f"{result.context.night_type.value} / {result.context.effective_mode.value}"
    sheet["P6"] = f"룰북 {rulebook_label(result.rules_version)}"
    sheet["U6"] = "검증 0건"
    for person, column in zip(people, ROSTER_COLUMNS):
        role = " (관리대행)" if person.is_manager and person.employee_id != "A" else ""
        sheet[f"{column}5"] = ("통제" if person.employee_id == "A"
                               else f"{_token(person)} {person.name}{role}")
    for address, label in HEADER_CELLS.items():
        sheet[address] = label
    sheet["A22"] = "특이사항"

    grouped = defaultdict(list)
    differences = []
    for assignment in result.record.assignments:
        person = people_by_id[assignment.employee_id]
        number = _token(person)
        row_number = 8 + assignment.slot.index
        column = _field_column(assignment.displayed_assignment)
        if not column:
            continue
        grouped[(row_number, column)].append(number)
        if (assignment.barrier_install_flag or assignment.barrier_remove_flag) and column != "AT":
            grouped[(row_number, "AT")].append(number)
        displayed = assignment.displayed_assignment.label
        actual = assignment.actual_post_or_work_type.label
        if displayed != actual and not (assignment.barrier_install_flag or assignment.barrier_remove_flag):
            hour = assignment.slot.hour
            differences.append(
                f"{hour:02d}시 {number} {PATROL_LABELS.get(displayed, displayed)}"
                f"→{PATROL_LABELS.get(actual, actual)}"
            )

    for index in range(14):
        hour = 18 + index if index <= 6 else index - 6
        sheet[f"A{8 + index}"] = f"{hour:02d}:00"
    for (row_number, column), numbers in grouped.items():
        numbers.sort(key=lambda item: (-1 if item == "A" else int(item)))
        cell = sheet[f"{column}{row_number}"]
        cell.value = ".".join(numbers)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sheet["F22"] = "표기/실제 차이: " + ", ".join(differences) if differences else "표기/실제 차이 없음"
    sheet["F22"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    sheet["F22"].font = Font(name="Arial", size=9)
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.print_area = "A1:BP24"

    _summary_sheet(workbook, result)
    _validation_sheet(workbook, result)
    _history_sheet(workbook, result)
    workbook.properties.title = "야간 근무 편성표"
    workbook.properties.subject = f"{day} {result.context.night_type.value}"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
