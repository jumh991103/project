/*
============================================================
화면 조회용 SQL 모음

이 파일의 SELECT문은 Streamlit 화면에서 사용한다.

:manufacturer_id, :model_id, :model_year, :variant_id는
Python에서 선택한 값을 넣어주는 이름 있는 파라미터다.

SQLite 터미널에서 테스트할 때는 숫자로 바꿔서 실행한다.
예: WHERE manufacturer_id = 1
============================================================
*/


/*
------------------------------------------------------------
1. 제조사 목록

화면의 첫 번째 선택 상자에 표시할 제조사를 가져온다.
------------------------------------------------------------
*/
SELECT
    manufacturer_id,
    manufacturer_name
FROM manufacturers
ORDER BY manufacturer_name;


/*
------------------------------------------------------------
2. 제조사 선택 후 대표 차종 목록

사용자가 고른 제조사에 속한 차종만 보여준다.
------------------------------------------------------------
*/
SELECT
    model_id,
    model_name,
    vehicle_type
FROM vehicle_models
WHERE manufacturer_id = :manufacturer_id
ORDER BY model_name;


/*
------------------------------------------------------------
3. 선택한 대표 차종의 원본 세부 차명

예: 카니발을 선택했을 때 카니발 YP, 카니발 KA4 등을 보여준다.
------------------------------------------------------------
*/
SELECT
    variant_id,
    variant_name
FROM vehicle_variants
WHERE model_id = :model_id
ORDER BY variant_name;


/*
------------------------------------------------------------
4. 선택한 차종에서 확인할 수 있는 모델연도

모델연도는 소비자 신고 데이터에만 있는 값이다.
------------------------------------------------------------
*/
SELECT DISTINCT
    model_year
FROM defect_reports
WHERE model_id = :model_id
  AND model_year IS NOT NULL
ORDER BY model_year DESC;


/*
------------------------------------------------------------
5. 선택한 모델연도의 소비자 결함 신고 건수

COUNT(*)는 원본 신고 행의 개수를 센다.
중복 신고도 원본 행으로 저장했기 때문에 포함된다.
------------------------------------------------------------
*/
SELECT
    COUNT(*) AS complaint_count
FROM defect_reports
WHERE model_id = :model_id
  AND model_year = :model_year;


/*
------------------------------------------------------------
6. 선택한 차종의 공식 리콜 목록

리콜 생산기간과 개시일, 대상 대수, 사유를 보여준다.

모델연도와 생산기간은 같은 기준이 아니므로
여기에는 model_year 조건을 직접 넣지 않는다.
------------------------------------------------------------
*/
SELECT
    recall_id,
    raw_model_name,
    production_start_date,
    production_end_date,
    recall_start_date,
    affected_count,
    recall_reason
FROM recalls
WHERE model_id = :model_id
ORDER BY recall_start_date DESC, recall_id DESC;


/*
------------------------------------------------------------
7. 선택한 세부 차명의 공식 리콜 목록

대표 차종보다 더 좁은 원본 차명 기준으로 조회한다.
------------------------------------------------------------
*/
SELECT
    recall_id,
    raw_model_name,
    production_start_date,
    production_end_date,
    recall_start_date,
    affected_count,
    recall_reason
FROM recalls
WHERE variant_id = :variant_id
ORDER BY recall_start_date DESC, recall_id DESC;


/*
------------------------------------------------------------
8. 차종별 요약 카드

model_overview VIEW에는 신고 수와 리콜 수가 이미 집계되어 있다.
화면의 요약 카드와 비교 화면에서 사용한다.
------------------------------------------------------------
*/
SELECT
    model_id,
    manufacturer_name,
    model_name,
    complaint_count,
    recall_record_count,
    affected_count_sum,
    latest_report_date,
    latest_recall_date
FROM model_overview
WHERE model_id = :model_id;


/*
------------------------------------------------------------
9. 모델연도별 신고 그래프 데이터

Streamlit의 막대그래프에 사용할 형태다.
판매량이 없는 단순 신고 건수이므로 결함률로 해석하지 않는다.
------------------------------------------------------------
*/
SELECT
    model_year,
    COUNT(*) AS complaint_count
FROM defect_reports
WHERE model_id = :model_id
  AND model_year IS NOT NULL
GROUP BY model_year
ORDER BY model_year;


/*
------------------------------------------------------------
10. 여러 차종 비교

2~5개 차종의 신고 수와 공식 리콜 기록 수를 비교한다.
IN 안의 ? 개수는 비교할 model_id 개수와 같아야 한다.
------------------------------------------------------------
*/
SELECT
    model_id,
    manufacturer_name,
    model_name,
    complaint_count,
    recall_record_count,
    affected_count_sum
FROM model_overview
WHERE model_id IN (?, ?, ?)
ORDER BY manufacturer_name, model_name;


/*
------------------------------------------------------------
11. FAQ 조회

활성화된 FAQ만 화면에 표시한다.
is_active가 1인 행만 가져온다.
------------------------------------------------------------
*/
SELECT
    category,
    question,
    answer,
    source_url
FROM faq_items
WHERE is_active = 1
ORDER BY sort_order, faq_id;
