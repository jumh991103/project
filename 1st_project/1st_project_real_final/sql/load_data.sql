/*
============================================================
전처리 CSV를 SQLite 테이블에 넣는 순서

이 파일은 다음 순서로 실행한다.

1. CSV 임시 테이블 생성
2. CSV 파일 import
3. 제조사 저장
4. 대표 차종 저장
5. 원본 세부 차명 저장
6. 소비자 신고 저장
7. 공식 리콜 저장

주의:
이 파일을 같은 DB에서 여러 번 실행하면 신고·리콜 행이
중복으로 추가될 수 있다. 다시 만들 때는 새 DB를 사용한다.
============================================================
*/


/*
------------------------------------------------------------
1. CSV 임시 테이블

전처리 CSV의 열을 그대로 받는 임시 공간이다.
여기서는 아직 model_id나 manufacturer_id를 붙이지 않는다.
------------------------------------------------------------
*/
DROP TABLE IF EXISTS defect_stage;
DROP TABLE IF EXISTS recall_stage;

CREATE TABLE defect_stage (
    received_date TEXT,
    manufacturer_name TEXT,
    model_name TEXT,
    model_year TEXT,
    vehicle_type TEXT
);

CREATE TABLE recall_stage (
    manufacturer_name TEXT,
    model_name TEXT,
    production_start_date TEXT,
    production_end_date TEXT,
    recall_start_date TEXT,
    affected_count TEXT,
    recall_reason TEXT,
    vehicle_type TEXT
);


/*
------------------------------------------------------------
2. CSV 파일 import

아래 두 줄은 일반 SQL이 아니라 SQLite 터미널 명령이다.
첫 번째 행은 CSV의 열 이름이므로 --skip 1로 건너뛴다.

SQLite 터미널에서 이 파일을 실행할 때 사용한다.
------------------------------------------------------------
*/
.mode csv
.import --skip 1 "data/processed/processed_data/자동차제작결함신고정보_11개제조사_패밀리카.csv" defect_stage
.import --skip 1 "data/processed/processed_data/차종별리콜대수_11개제조사_패밀리카.csv" recall_stage


/*
------------------------------------------------------------
3. 제조사 저장

신고 파일과 리콜 파일의 제조사를 합친 뒤,
같은 제조사는 한 번만 manufacturers에 저장한다.
------------------------------------------------------------
*/
INSERT OR IGNORE INTO manufacturers (
    manufacturer_name,
    manufacturer_key
)
SELECT DISTINCT
    TRIM(manufacturer_name),
    LOWER(
        REPLACE(
            REPLACE(TRIM(manufacturer_name), ' ', ''),
            '-', ''
        )
    )
FROM (
    SELECT manufacturer_name FROM defect_stage
    UNION ALL
    SELECT manufacturer_name FROM recall_stage
)
WHERE TRIM(manufacturer_name) <> '';


/*
------------------------------------------------------------
4. 대표 차종 저장

신고·리콜 두 파일에 등장하는 차명을 모아서 저장한다.
model_key는 공백과 하이픈을 뺀 비교용 값이다.

이 키는 간단한 표기 차이만 줄여준다.
한국어·영문 차명을 완전히 같은 차종으로 합치는 작업은
별도 매핑이 필요하다.
------------------------------------------------------------
*/
WITH all_models AS (
    SELECT manufacturer_name, model_name, vehicle_type
    FROM defect_stage

    UNION ALL

    SELECT manufacturer_name, model_name, vehicle_type
    FROM recall_stage
),
normalized_models AS (
    SELECT
        TRIM(manufacturer_name) AS manufacturer_name,
        TRIM(model_name) AS model_name,
        LOWER(
            REPLACE(
                REPLACE(TRIM(model_name), ' ', ''),
                '-', ''
            )
        ) AS model_key,
        MAX(TRIM(vehicle_type)) AS vehicle_type
    FROM all_models
    WHERE TRIM(manufacturer_name) <> ''
      AND TRIM(model_name) <> ''
    GROUP BY
        TRIM(manufacturer_name),
        TRIM(model_name)
)
INSERT OR IGNORE INTO vehicle_models (
    manufacturer_id,
    model_name,
    model_key,
    vehicle_type
)
SELECT
    m.manufacturer_id,
    n.model_name,
    n.model_key,
    n.vehicle_type
FROM normalized_models n
JOIN manufacturers m
  ON m.manufacturer_name = n.manufacturer_name;


/*
------------------------------------------------------------
5. 원본 세부 차명 저장

대표 차종 아래에 원본 차명을 연결한다.
상세 화면에서 실제 데이터의 차명을 보여줄 때 사용한다.
------------------------------------------------------------
*/
INSERT OR IGNORE INTO vehicle_variants (
    model_id,
    variant_name,
    variant_key
)
SELECT DISTINCT
    vm.model_id,
    TRIM(s.model_name),
    LOWER(
        REPLACE(
            REPLACE(TRIM(s.model_name), ' ', ''),
            '-', ''
        )
    )
FROM (
    SELECT manufacturer_name, model_name FROM defect_stage
    UNION
    SELECT manufacturer_name, model_name FROM recall_stage
) s
JOIN manufacturers m
  ON m.manufacturer_name = TRIM(s.manufacturer_name)
JOIN vehicle_models vm
  ON vm.manufacturer_id = m.manufacturer_id
 AND vm.model_key = LOWER(
        REPLACE(
            REPLACE(TRIM(s.model_name), ' ', ''),
            '-', ''
        )
    );


/*
------------------------------------------------------------
6. 소비자 결함 신고 저장

신고 원본 행은 중복 제거하지 않고 모두 저장한다.
model_year는 신고 데이터에 있는 모델연도이고,
리콜 생산기간과 직접 연결하지 않는다.
------------------------------------------------------------
*/
INSERT INTO defect_reports (
    model_id,
    variant_id,
    source_manufacturer_name,
    raw_model_name,
    received_date,
    model_year,
    vehicle_type,
    source_file
)
SELECT
    vm.model_id,
    vv.variant_id,
    TRIM(s.manufacturer_name),
    TRIM(s.model_name),
    NULLIF(TRIM(s.received_date), ''),
    CAST(NULLIF(TRIM(s.model_year), '') AS INTEGER),
    NULLIF(TRIM(s.vehicle_type), ''),
    '자동차제작결함신고정보_11개제조사_패밀리카.csv'
FROM defect_stage s
JOIN manufacturers m
  ON m.manufacturer_name = TRIM(s.manufacturer_name)
JOIN vehicle_models vm
  ON vm.manufacturer_id = m.manufacturer_id
 AND vm.model_key = LOWER(
        REPLACE(
            REPLACE(TRIM(s.model_name), ' ', ''),
            '-', ''
        )
    )
JOIN vehicle_variants vv
  ON vv.model_id = vm.model_id
 AND vv.variant_name = TRIM(s.model_name);


/*
------------------------------------------------------------
7. 공식 리콜 저장

리콜 생산기간, 리콜 개시일, 대상 대수, 사유를 저장한다.
affected_count의 쉼표를 제거한 뒤 숫자로 변환한다.
------------------------------------------------------------
*/
INSERT INTO recalls (
    model_id,
    variant_id,
    source_manufacturer_name,
    raw_model_name,
    production_start_date,
    production_end_date,
    recall_start_date,
    affected_count,
    recall_reason,
    vehicle_type,
    source_file
)
SELECT
    vm.model_id,
    vv.variant_id,
    TRIM(s.manufacturer_name),
    TRIM(s.model_name),
    NULLIF(TRIM(s.production_start_date), ''),
    NULLIF(TRIM(s.production_end_date), ''),
    NULLIF(TRIM(s.recall_start_date), ''),
    CAST(
        NULLIF(REPLACE(TRIM(s.affected_count), ',', ''), '')
        AS INTEGER
    ),
    NULLIF(TRIM(s.recall_reason), ''),
    NULLIF(TRIM(s.vehicle_type), ''),
    '차종별리콜대수_11개제조사_패밀리카.csv'
FROM recall_stage s
JOIN manufacturers m
  ON m.manufacturer_name = TRIM(s.manufacturer_name)
JOIN vehicle_models vm
  ON vm.manufacturer_id = m.manufacturer_id
 AND vm.model_key = LOWER(
        REPLACE(
            REPLACE(TRIM(s.model_name), ' ', ''),
            '-', ''
        )
    )
JOIN vehicle_variants vv
  ON vv.model_id = vm.model_id
 AND vv.variant_name = TRIM(s.model_name);
