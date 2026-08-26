/*
============================================================
SQLite 데이터 적재 결과 확인용 SQL

이 파일은 데이터를 수정하지 않는다.
행 수, 제조사 수, 요약 VIEW 결과를 확인하는 용도다.

예상되는 주요 값:
신고 데이터 18,492행
리콜 데이터 1,516행
제조사 11개
============================================================
*/


/*
------------------------------------------------------------
1. 테이블과 VIEW가 만들어졌는지 확인
------------------------------------------------------------
*/
SELECT
    name,
    type
FROM sqlite_master
WHERE type IN ('table', 'view')
ORDER BY type, name;


/*
------------------------------------------------------------
2. 임시 CSV 테이블 행 수 확인

CSV import가 제대로 되었는지 먼저 확인한다.
------------------------------------------------------------
*/
SELECT
    'defect_stage' AS table_name,
    COUNT(*) AS row_count
FROM defect_stage

UNION ALL

SELECT
    'recall_stage',
    COUNT(*)
FROM recall_stage;


/*
------------------------------------------------------------
3. 최종 신고·리콜 행 수 확인

전처리 CSV의 행 수와 비교한다.
신고 18,492행, 리콜 1,516행이 기준이다.
------------------------------------------------------------
*/
SELECT
    'defect_reports' AS table_name,
    COUNT(*) AS row_count
FROM defect_reports

UNION ALL

SELECT
    'recalls',
    COUNT(*)
FROM recalls;


/*
------------------------------------------------------------
4. 제조사 개수 확인

현재 프로젝트의 범위는 11개 제조사다.
------------------------------------------------------------
*/
SELECT COUNT(*) AS manufacturer_count
FROM manufacturers;


/*
------------------------------------------------------------
5. 제조사별 신고·리콜 행 수

어느 제조사의 데이터가 많이 들어갔는지 확인한다.
------------------------------------------------------------
*/
SELECT
    m.manufacturer_name,
    (
        SELECT COUNT(*)
        FROM defect_reports d
        JOIN vehicle_models vm1
          ON vm1.model_id = d.model_id
        WHERE vm1.manufacturer_id = m.manufacturer_id
    ) AS defect_count,
    (
        SELECT COUNT(*)
        FROM recalls r
        JOIN vehicle_models vm2
          ON vm2.model_id = r.model_id
        WHERE vm2.manufacturer_id = m.manufacturer_id
    ) AS recall_count
FROM manufacturers m
ORDER BY m.manufacturer_name;


/*
------------------------------------------------------------
6. 대표 차종과 세부 차명 개수

차종 연결이 정상적으로 되었는지 확인한다.
------------------------------------------------------------
*/
SELECT
    (SELECT COUNT(*) FROM vehicle_models) AS model_count,
    (SELECT COUNT(*) FROM vehicle_variants) AS variant_count;


/*
------------------------------------------------------------
7. 차종 요약 VIEW 확인

신고 수가 많은 차종을 20개까지 확인한다.
------------------------------------------------------------
*/
SELECT
    manufacturer_name,
    model_name,
    complaint_count,
    recall_record_count,
    affected_count_sum
FROM model_overview
ORDER BY complaint_count DESC
LIMIT 20;


/*
------------------------------------------------------------
8. 신고·리콜 연결 누락 확인

정상이라면 결과가 0이어야 한다.
------------------------------------------------------------
*/
SELECT COUNT(*) AS defect_without_model
FROM defect_reports
WHERE model_id IS NULL;

SELECT COUNT(*) AS recall_without_model
FROM recalls
WHERE model_id IS NULL;


/*
------------------------------------------------------------
9. 날짜 범위 확인

신고 데이터는 접수일자,
리콜 데이터는 리콜 개시일을 기준으로 확인한다.
------------------------------------------------------------
*/
SELECT
    '소비자 결함 신고' AS dataset_name,
    MIN(received_date) AS start_date,
    MAX(received_date) AS end_date,
    COUNT(*) AS row_count
FROM defect_reports

UNION ALL

SELECT
    '공식 리콜',
    MIN(recall_start_date),
    MAX(recall_start_date),
    COUNT(*)
FROM recalls;


/*
------------------------------------------------------------
10. 리콜 대수와 리콜 기록 수의 의미 확인

recall_record_count는 리콜 기록 개수이고,
affected_count_sum은 리콜 기록별 대상 대수의 합계다.
합계는 동일 차량이 여러 번 포함될 수 있으므로
고유 차량 대수로 해석하지 않는다.
------------------------------------------------------------
*/
SELECT
    model_id,
    model_name,
    recall_record_count,
    affected_count_sum
FROM model_overview
WHERE recall_record_count > 0
ORDER BY affected_count_sum DESC
LIMIT 20;
