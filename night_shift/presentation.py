"""Read-only labels shared by the Streamlit and Excel presentations."""

from .models import AssignmentKind, Posture


PATROL_LABELS = {"upper": "상층", "middle": "중층", "lower": "하층"}
NIGHT_TYPE_LABELS = {
    "N1": "N1 (평일 → 평일)",
    "N2": "N2 (평일 → 공휴일)",
    "N3": "N3 (공휴일 → 평일)",
    "N4": "N4 (공휴일 → 공휴일)",
}
POSTURE_LABELS = {
    Posture.STANDING: "입식", Posture.SEATED: "좌식", Posture.REST_LIKE: "휴게성",
}


def night_type_label(value) -> str:
    key = getattr(value, "value", value)
    return NIGHT_TYPE_LABELS.get(str(key), str(key))


def actual_state_label(row) -> str:
    """Short, explicit actual-state label for the employee timeline."""
    if row.actual_post_or_work_type.kind == AssignmentKind.PATROL:
        return PATROL_LABELS.get(row.actual_post_or_work_type.label,
                                 row.actual_post_or_work_type.label)
    if row.actual_rest_time_value == 1:
        if row.displayed_assignment.kind == AssignmentKind.SECURITY_STANDBY:
            return "보안실 대기"
        return "휴게성"
    if row.barrier_install_flag:
        return "차단봉 설치"
    if row.barrier_remove_flag:
        return "차단봉 철수"
    return row.actual_post_or_work_type.label


def assignment_view(row, context=None) -> tuple[str, tuple[str, ...], str, str]:
    """Return display text, notes, color and category from one recorded row.

    context를 주면 유도리 포스트별 운영(사용자 지정)으로 휴게성·좌식이 된 칸에 메모를 단다.
    룰북 기본 유도리(I1 00~03시 휴게성)는 굵은 00~04 띠로만 표시한다.
    """
    kind = row.displayed_assignment.kind
    label = row.displayed_assignment.label
    notes = []
    if row.barrier_install_flag:
        notes.append("차단봉 설치")
    if row.barrier_remove_flag:
        notes.append("차단봉 철수")
    actual = row.actual_post_or_work_type.label
    if kind == AssignmentKind.UNAVAILABLE:
        return "×", (), "F8FAFC", "근무불가"
    run_as_rest = kind == AssignmentKind.POST and row.actual_rest_time_value == 1
    if (actual != label and not (row.barrier_install_flag or row.barrier_remove_flag)
            and not (run_as_rest and actual.endswith("휴게성"))):
        # 유도리 휴게성 포스트는 굵은 띠·'휴게성' 메모로 따로 표시. 평일 시작 야간 통제 18시 L3처럼
        # 실제로는 보안실 대기인 칸은 '실제 보안실 대기'를 적는다 (2026-10-02 사용자 요청).
        notes.append("실제 " + PATROL_LABELS.get(actual, actual))
    custom = context is not None and context.post_operations is not None
    slot = row.slot.index
    # 유도리 운영으로 휴게성이 된 칸만 ('… 휴게성'). 18시 관리자 L3(보안실 대기) 같은 다른 휴게성 칸은 그대로.
    if run_as_rest and actual.endswith("휴게성") and (custom or not (label == "I1" and 6 <= slot <= 9)):
        notes.append("휴게성")
    elif (custom and kind == AssignmentKind.POST and row.posture_or_mode == Posture.SEATED
          and (label in ("L3", "G2", "G3", "G2(1)") or label == "G1" and not 6 <= slot <= 10)):
        notes.append("좌식")
    if row.barrier_install_flag or row.barrier_remove_flag:
        return PATROL_LABELS.get(label, label), tuple(notes), "FBCFE8", "차단봉"
    if kind == AssignmentKind.PATROL:
        return PATROL_LABELS.get(label, label), tuple(notes), "DDD6FE", "순찰"
    if kind == AssignmentKind.REST:
        return label, tuple(notes), "E5E7EB", "휴게"
    if kind == AssignmentKind.SECURITY_STANDBY:
        return label, tuple(notes), "DBEAFE", "보안실"
    if label in ("G2", "G3", "G2(1)"):
        return label, tuple(notes), "FECACA", "남문"
    if label == "G1":
        return label, tuple(notes), "BBF7D0", "G1"
    if label == "L3":
        return label, tuple(notes), "BFDBFE", "L3"
    if label == "I1":
        return label, tuple(notes), "FDE68A", "I1"
    return label, tuple(notes), "DCFCE7", "포스트"


def flexible_band(context) -> tuple[int, int] | None:
    """Slots (inclusive) of the 00~04 block outlined in bold on flexible (유도리) schedules."""
    from .models import Mode, mode_at
    if context.post_operations is not None:      # 사용자 지정 유도리: 띠 대신 칸마다 '휴게성'·'좌식' 메모
        return None
    start = next((t for t in range(6, 11) if mode_at(context, t) == Mode.FLEXIBLE), None)
    return (start, 10) if start is not None else None


def run_text(windows) -> str:
    return "; ".join(
        f"{(18 + w.start_index) % 24:02d}~{(18 + w.end_index_exclusive) % 24:02d}시 "
        + " → ".join(f"{label}({POSTURE_LABELS[posture]})" if posture else label
                     for label, posture in zip(w.display_labels, w.postures))
        for w in windows
    )
