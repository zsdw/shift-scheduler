# RULE_INDEX.md — 야간근무 룰북 v2.21 개발 색인

현재 유효한 색인만 둔다(2026-10-13 정리, 이전 원본 `backup/docs_cleanup_20261013/docs/RULE_INDEX.md`). 날짜별 기록은 CHANGELOG.
평일 주간은 `docs/평일_주간근무_룰북_v1.0.txt`, 주말 주간은 `docs/주말_주간_룰북_v1.0.md`(구현 `night_shift/weekend_day.py`), 일보·명령서는 `docs/업무문서_계산기준.md`.

이 문서는 룰북을 대체하지 않는다. AI/개발자가 관련 조항을 빠르게 찾기
위한 색인이다. 정확한 규칙은 항상 `야간근무_룰북_v2.21.txt` 본문을 직접
확인한다.

  ---------------------------------------------------------------------------
  영역                        룰북 위치               구현에서 우선 확인할 곳
  --------------------------- ----------------------- -----------------------
  최상위 원칙·모드·우선순위   제0장                   context/config,
                                                      service, solver
                                                      objective

  N1\~N4 정의                 제1장                   calendar/type
                                                      resolution,
                                                      presentation

  인원·결원·A/준호 관리자     제2장                   models/context, service
  상태                                                

  시간 슬롯·기본              제3장                   solver, validator
  포스트·보안실                                       

  표시근무/실제근무 데이터    제4장                   models, analysis,
  모델                                                history

  남문 운영                   제5장                   solver, validator,
                                                      presentation

  18\~19 L3/I1 특수운영       제6장                   solver, validator

  07시 I1 실제근무 해석       제7장                   solver, validator,
                                                      analysis

  관리자 후반부·최소부담      제8장                   solver objective,
                                                      validator, manager
                                                      tests

  동일포스트·연속근무·자세    제9장 및 관련 HARD      solver, validator,
                                                      hard-rule tests

  식사기회                    관련 식사 조항          solver, validator

  유도리 모드                 유도리 전용 장          mode profile, solver,
                                                      validator

  FM 모드                     FM 전용 장              mode profile, solver,
                                                      validator

  순찰·순찰 후 회복           순찰 장 / H-11          solver, validator,
                                                      patrol tests

  차단봉                      제15장                  solver, history,
                                                      validator

  마지막 휴게                 제16장                  solver, history,
                                                      validator

  당일 밸런스                 제17장                  solver objective,
                                                      analysis

  장기이력·soft debt          제18장                  history store, solver
                                                      objective

  생성 전 체크                제19장                  service/UI input
                                                      validation

  실제 이력 확정              제20장                  history confirmation

  Validator·INFEASIBLE·긴급   제21장                  service, solver,
  재편성                                              validator, UI

  부분가용/LOCK/정규화        21-7                    availability model,
                                                      reoptimization

  긴급 최소완화 진단          21-8                    relaxation diagnostics,
                                                      UI, validator

  출력/Excel                  제22장                  presentation, excel
                                                      exporter

  권장 구현 구조              제23장                  project architecture

  버전 변경내역               제24장                  migration/reference
                                                      only

  전수검증 목록               제25장                  pytest matrix
  ---------------------------------------------------------------------------

## v2.21 (문서 정리)

-   '관리자 상태에 따른 준호 신분'은 8-8. 8-7은 결원 2명 관리자 정책만.
-   관리자 최소부담 우대·격차 상한은 결원 0/1명에만. 결원 2명(정식, 0-4-1,
    0-4-2)은 8-7. 관리자 고정규칙은 항상 유지.
-   N1/N3 07시 가용 일반근무자 4명이면 8-3-1(관리자 07시 L3/I1).
-   제25장 검증목록은 위 기준으로 수정됨. 옛 문구로 테스트를 만들지 않는다.

## v2.20에서 특히 주의할 항목

-   0-4-2 전환은 서비스 `run_reoptimization`에서만 설정한다. Validator는
    `reoptimization=True`일 때만 허용하고, 전환 이후 남은 가용
    일반근무자가 4명 이하인지 확인한다.
-   모드는 슬롯별(`mode_at`). 남문·차단봉 설치자·I1 회계·순찰 후 휴게가
    슬롯의 모드와 결원 프로필을 따른다.
-   H-11-2 보호 순찰은 Solver에서 보호 플래그 + 등급 목적함수, Validator에서
    "사람별 보호 순찰 1회 이상"으로 독립 검증한다.

## v2.19에서 특히 주의할 항목

-   8-4-2 방향성 격차(A가 0~2점 낮게)는 A 출근 + 결원 0/1명,
    전체가용 일반근무자에게만 적용한다. 준호 대행·결원 2명은 제외.
-   재생성 다양성 조건은 Solver의 `exclude_assignments` 처리에서
    일반근무자 줄의 모든 순열에 대해 적용한다(rules_v219).

## v2.18에서 특히 주의할 항목

-   0-4-1 부분가용 결원 판정은 `solver.planned_vacancy()`와 Validator의
    독립 계산이 같은 결과를 내야 한다. 결과는
    `ShiftContext.partial_vacancy_profile`에 기록된다.
-   결원 2명 프로필은 `CommonPolicy.profile_general_count`로 전달된다.
    남문·차단봉 설치자(I1)·H-11 완화형이 여기에 따른다.
-   8-7 관리자 정책은 목적함수(`manager_barrier_avoidance`)와 H-15/8-4-2
    해제로 구현된다. 05시 휴게·06시 G2 HARD는 그대로다.
-   8-3-1은 07시 가용 일반근무자 수(관리자대행 제외)로 판정한다.
-   긴급 재편성(LOCK 있음)에서는 0-4-1 판정을 하지 않는다.

## v2.17에서 특히 주의할 항목

-   A 정상 출근과 준호 관리자대행의 목적함수를 동일하게 구현하면 안
    된다.
-   A 출근: A 실근무시간 최소만 관리자 우대.
-   준호 대행: 준호 실근무시간 최소 후 동률 시 준호 피로도 최소.
-   이 변경은 기존 관리자 HARD 삭제가 아니다.
-   N1/N3 관리자 05 휴게 → 06 G2 → 07 휴게 HARD 유지.
-   관리자 04 I1은 저우선 SOFT 유지.
-   긴급 재편성에서 미래 일반근무자 가용인원이 4명으로 감소하면
    FM→유도리 자동전환 경로를 확인한다.
-   LOCK 경계에서 연속근무/동일포스트/순찰후회복 판정을 초기화하지
    않는다.


## 조항별 구현 위치 (생성 · 독립 검증 · 회귀검사)

| 규칙/표시 | 생성·집계 | 독립 검증/회귀검사 |
|---|---|---|
| 통제A 04시 보안실 대기 금지·철수 불참(8-10, 하드 — 옛 17-1 04시 회피를 대체) | 아래 8-10 줄 참고 / 개인 회피는 preferences.avoid_cells·`personal_avoid` | tests/test_preferences.py |
| 편성표 일괄 가져오기·연차일정 기본 상태·기타 | night_shift/bulk_import.py · leave_schedule.py · import_ui.render_bulk/render_leave_text · app.apply_night_leave_defaults · day_ui._leave_defaults | tests/test_bulk_leave.py |
| 실근무 = 포스트·순찰만(11-0) | profiles.make_record / validator 기대값 / history_store.record_from_json(저장본 재계산) | tests 전체(회계) |
| 야간 포스트 고루 배정(17-2) | solver `post_coverage`(관리자 우대 앞)·`post_spread`(general_balance 다음) / balance_notes `_coverage_lines` | tests/test_post_coverage.py |
| 직원 비교표 순찰 피로도·기타 피로도(화면) | service `patrol_fatigue`·`other_fatigue`·`other_fatigue_reasons`·`patrol_reasons` / app `SUMMARY_COLUMNS`·`_other_fatigue_text`·`_patrol_text` | tests/test_other_fatigue.py, test_staff_detail.py |
| 긴급 반차 접힌 칸·LOCK 끄기 취소(화면) | history_ui `emergency_toggle`·`emergency_box` / app·day_ui 호출부 | tests/test_mobile_ui.py, test_emergency_toggle.py |
| 미리 정한 야간 반차자(H-09-1): 순찰 후 휴게 하드 아님·휴게 합계 2시간 하드 | solver `half_day`(순찰 블록·휴게 2시간·`half_day_patrol_rest`) / service `half_day_ids`(재편성) / validator `H-09-1` | tests/test_half_day_rules.py |
| 차단봉 담당(15-0, 하드): 2026-10-09 야간부터 단독 — 20시 G2 혼자(없으면 I1 혼자)·04시 I1 혼자·대기자 없음, 10/05~10/08은 G2/I1+대기 1명, 집계는 10/04 야간부터 | models `barrier_v2`·`BARRIER_SINGLE_FROM`·`BARRIER_HISTORY_FROM` / profiles `options_for`·`make_record` / solver 설치 인원·통제 제외 / validator `15-0`(기준일 각자) / bulk_import·schedule_image_import | tests/test_barrier_single.py, test_barrier_v2.py, test_barrier_history_start.py |
| 차단봉 연속 회차 설치 금지(15-3, 하드, 10/19): 직전 회차 설치자(G2·I1) 이번 설치 불가, LOCK 보존 / 차단봉 마지막 참여일 순(15-8, 10/19): 설치·철수 중 마지막 날이 오래된 사람부터, 막타임 다음 최우선, 횟수 기준 폐지 | service `derived_forbid` / solver `forbid_install_ids`·`barrier_oldest_*` / validator `15-3` / balance_notes 15-8 문구 | tests/test_barrier_consecutive_install.py |
| 하층 순찰 순번(14-7, 10/19): 야간+공휴일 주간 이력, 마지막 하층 뒤 상·중층 순찰 출근 3회 이상이면 후보, 마지막 하층 오래된 순, 막타임→차단봉 다음. 종전 2회 기준·18-9 soft debt·14-8 하층 횟수 비교 대체 | patrol_history `zones`·`WEEKEND_ZONES` / soft_history `lower_patrol_wait` / solver `lower_oldest_*` / balance_notes 14-7 문구 | tests/test_lower_patrol_order.py |
| 순찰 층 이력 합산(10/20): 14-7·14-8·14-9 모두 야간+공휴일 주간 순찰 이벤트(zones)로 셈, 주말 엔진도 동일 | service `mixed_zone_rates` / solver·validator 14-9 이벤트 우선 / weekend_day `_lower_streak_events`·`lower_rank`·`zone_cost` | tests/test_patrol_mixed_zones.py |
| 대행 준호 최저·관리자 하대 금지(10/20, 하드): 하루 종일 대행 준호 ≤ 일반근무자 최저, 결원 2명 통제A ≤ 일반근무자 최고. 대행 날 2회 순찰 관리자 선호 없음. 장부에 대행 준호 적립 | solver `full_proxy_low_general_fatigue`·`vacancy_manager_top_general_fatigue` / validator '대행준호-최저피로도'·'관리자-하대금지' / fatigue_ledger `night_extras` | tests/test_proxy_lowest.py |
| 소프트 목표 순서 (가)(10/20): 가능하면 지킬 규칙 → 막타임 → 차단봉 → 하층 → 당일 균형 → 장부 → 기타 | solver 장부 재배치 블록 / weekend_day 순번 고정 | 룰북 0-6 |
| 일반근무자 실근무 차이 최대 1시간(H-18, 하드) | solver(H-17 다음, `full_general_ids` 쌍별 제약) / validator `H-18`(`work_spread`, 유도리 참고 표는 끔) | tests/test_work_spread.py |
| 추가 남문 G2 생성 전 확인(5-7) | app `extra_south_input`(생성 버튼 잠금) / models `extra_south_choices`·ShiftContext `extra_south_slots` / common 필수 포스트 / validator `§5-7`·남문 기대값 / history_store 저장 | tests/test_extra_south.py |
| 관리자 18·07시 근무 없음(8-11, 하드, 8-3-1 예외) | solver(8-10 다음, `manager_works_07`면 07시 제외) / validator `8-11` | tests/test_manager_first_last.py |
| 통제A 04시 보안실 대기·I1 금지·철수 불참(8-10, 하드; 8-6 04시 I1 선호는 삭제·분석 표시도 제거) | solver(6-2-1 다음, LOCK된 04시 제외) / validator `8-10`(재편성 제외) | tests/test_manager_04_rest.py, test_a04_i1.py |
| 통제A 순찰 직후 근무 허용(H-12-1, 하드)·새벽 연속 휴게 2시간(17-4) | solver 순찰 후 휴게 블록(A·t=3) / `manager_late_two_hour_rest` 목적(관리자 우대 다음) / validator `H-12-1` | tests/test_manager_patrol_rest.py |
| 주말 시작 통제A 18시 휴게(6-2-1, 하드) | solver(H-17 블록 다음, LOCK된 18시 제외) / validator `6-2-1`(재편성 제외) | tests/test_post_cap.py |
| 같은 포스트 한 회차 최대 3번(H-17, 하드, 평일 18시 통제 L3 표기 제외) | solver `post_cap`(LOCK 앞 초과분 보존) / validator `post_cap`(따로 계산) / service `run_schedule`(2명 완전결원+INFEASIBLE 때만 `relax_post_cap` 재시도·`post_cap_relaxed`) / app 특이사항 | tests/test_post_cap.py |
| 가져온 기록의 반차·연차 = 근무불가(21-7) | history_import `apply_leave`·`leave_fix_record` / bulk_import `night_record(leave)` / import_ui / tools_leave_fix.py | tests/test_import_leave.py |
| 야간 밸런스 판정 표시(17-3) | balance_notes `balance_verdict` (완성표만 보고 계산, Solver 단계 상태로 시간 부족 구분) | tests/test_post_coverage.py |
| 순수 입식·좌식/특수업무 피로도 | service.calculate_employee_stats, app.person_actual_state, presentation.run_text | tests/test_staff_detail.py |
| PC 최장 구간/모바일 3열 | app.person_timeline_html / person_schedule_html | tests/test_staff_detail.py |
| 주간 전환 간 비포스트(28) | day_shift._solve_day / _reoptimize_day | _check_day, tests/test_day_rotation_policy.py |
| 주간 하드 다음 순환 권장 | _rotation_cost / _solve_priorities | rotation_advisories / 우선순위 CP 회귀검사 |
| 주간 조건부 A 일반 편입·LOCK | solve_day / reoptimize_day / control_active | _check_day / JSON 왕복·UNKNOWN 회귀검사 |

§28은 주간 §3-2 완화·§26 A 절대 미편입·§27 미래 A/E 메움보다 우선한다. 기존 고정틀과 과거 LOCK은 유지한다.
| 결원 2명 조장-일반 평균 피로도 차이 4점 초과 최소화(17-5, 권장) | solver 목표 단계(일반근무자 밸런스 다음) / balance_notes 비고 | tests/test_vacancy_manager_gap.py |
| 다음날 공휴일 + 결원2 관리자 06·07시 휴게/업무 없는 대기(8-12, 하드) | solver / validator `8-12` | tests/test_manager_holiday_end.py |
| 유도리 포스트별 운영(10-1-1) | models `post_operation` → profiles `make_record` / validator `_expected_operation`(따로) / app 사이드바 | tests/test_flexible_operations.py, test_operations_sidebar.py |
| FM·유도리 동시 만족 우선(0-2-1) | solver `dual_flexible`·`dual_balance` / service `run_schedule`·`flexible_view`·`daily_spreads` | tests/test_dual_mode.py |
| 사람별 부담 비고 = 과거 싸이클 영향만 | balance_notes `history_influence_lines` | tests/test_history_influence.py, test_balance_notes.py |
| 현장 양식 특이사항 칸·흡연장 파라솔 | schedule_image `field_duty_notes`·`parasol` | tests/test_field_notes.py |

- 8-13: 공휴일 전날 관리자(통제A·준호 대행) 06시 G1 금지 — solver.solve_first_trial / validator.validate_first_trial / tests.test_manager_holiday_g1
- 17-6: 최근 2싸이클 야간 1점 보상 — service.prepare_engine_inputs / solver.solve_first_trial / balance_notes.history_influence_lines / tests.test_night_compensation

- H-19: 마지막 05·06·07시 3연속 실휴게 금지(통제A·준호 관리자대행 예외) — solver.solve_first_trial / validator.validate_first_trial / tests.test_last_three_rest
- 관리자 교대 경계(준호 연속근무, 0-4-3·0-4-4): solver handover_boundary(하드, rule_off '교대 경계(준호 연속근무)') / 독립 검사 service.handover_boundary_issues / tests.test_manager_late_half·test_manager_early_half
- 8-10-1: 관리자(통제A·준호 대행) 04시 비우기 → 05·06시 관리자 실근무 최소(아주 강한 권장, 가능하면 지킬 규칙 다음·막타임 앞) — solver 목표 manager_04_rest·manager_0506_work / tests.test_manager_0400_rest
- H-20: 일반근무자 06·07시 연속 휴게 금지(통제A·준호 관리자대행 예외, 결원 무관, FM 표기) — solver.solve_first_trial / validator.validate_first_trial / service.RULE_GROUPS / tests.test_last_two_rest. 빨간날 주간 16·17시는 weekend_day.generate·_check


- 14-1-2 야간·공휴일 주간 통합 순찰 보호/제외 회전: `patrol_history.load_events`, `history_store.history_selection`, `service.prepare_engine_inputs`, `solver.solve_first_trial`, `validator.validate_first_trial`, `weekend_day.generate/validate/reoptimize`.
- 14-9 야간 하층 3회 연속 금지: `solver.solve_first_trial`, `validator.validate_first_trial`, `service.PreparedEngineInputs.patrol_actuals`.

- 5-3-1 다음날 평일 남문 연속 금지: `solver.solve_first_trial`, `validator.validate_first_trial`, `schedule_edit.RULE_HINTS`, `tests/test_south_pair_weekday.py`.

- 16장 막타임 수혜일 우선/다음 출근 금지: `HistorySelection.last_rest_records`, `history_store.history_selection`, `solver.solve_first_trial`(last_rest_oldest 단계), `validator.validate_first_trial`(16-next), `history_ui.last_rest_table_html`, `tests/test_last_rest_recency.py`.

- 12-3 순찰 후 세 번째 비포스트 휴게 대기 표기·대기 연속 회피: `solver.solve_first_trial`(patrol_third_standby/avoid_consecutive_standby), `validator.validate_first_trial`(12-third/12-protected), `tests/test_patrol_third_standby.py`.

- 12-4 비포스트3시간 연속휴게2칸·전체 대기부담 분산: `solver.solve_first_trial`(plain_rest_left/right, standby_total_load), `validator.validate_first_trial`(12-block), `tests/test_standby_three_block.py`.

- 12-5 결원2명 외18~05시 대기 최소1명: `solver.solve_first_trial`(required_standby_slots), `validator.validate_first_trial`(12-required), `tests/test_required_standby.py`.

- 12-6 통제A 제외 대기 횟수 차이<=1: `solver.solve_first_trial`(standby_totals/standby_total_load), `validator.validate_first_trial`(12-gap), `tests/test_standby_gap.py`.

- 8-14 통제A 야간I1 최소1회: `solver.solve_first_trial`, `validator.validate_first_trial`, `tests/test_a_i1_once.py`.

- 8-15 통제A 대기 최대2회: `solver.solve_first_trial`, `validator.validate_first_trial`, `tests/test_a_standby_cap.py`.
