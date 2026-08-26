/*
============================================================
중고차 리콜체크 SQLite 데이터베이스 구조

이 파일은 데이터를 넣는 파일이 아니다.
제조사, 차종, 신고, 리콜 데이터를 담을 "그릇"을 만든다.

데이터 입력은 나중에 load_data.sql 또는 Python 코드에서 진행한다.
============================================================
*/

-- 테이블끼리 연결된 ID가 실제로 존재하는지 검사한다.
PRAGMA foreign_keys = ON;


/*
------------------------------------------------------------
1. manufacturers: 제조사 기본 정보

예: 현대자동차, 기아, BMW, 볼보

manufacturer_id는 DB 내부에서 사용하는 번호이고,
manufacturer_name은 화면에 표시하는 이름이다.
manufacturer_key는 이름 비교·중복 방지용 키다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS manufacturers (
    manufacturer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_name TEXT NOT NULL UNIQUE,
    manufacturer_key TEXT NOT NULL UNIQUE
);


/*
------------------------------------------------------------
2. vehicle_models: 화면에 보여줄 대표 차종

예: 카니발, 쏘렌토, 싼타페, XC90

제조사 하나는 여러 차종을 가질 수 있다.
manufacturer_id가 manufacturers 테이블과 연결된다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS vehicle_models (
    model_id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_key TEXT NOT NULL,
    vehicle_type TEXT,

    -- 같은 제조사 안에서 같은 차종 키를 중복 저장하지 않는다.
    UNIQUE (manufacturer_id, model_key),

    -- 존재하지 않는 제조사 ID가 들어가는 것을 막는다.
    FOREIGN KEY (manufacturer_id)
        REFERENCES manufacturers(manufacturer_id)
);


/*
------------------------------------------------------------
3. vehicle_variants: 원본 세부 차명

예: 카니발 YP, 카니발 KA4, GLA45 AMG 4Matic

대표 차종으로 검색한 뒤 원본 차명을 자세히 보여줄 때 사용한다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS vehicle_variants (
    variant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL,
    variant_name TEXT NOT NULL,
    variant_key TEXT NOT NULL,

    -- 같은 대표 차종 안에서 같은 원본 차명은 한 번만 저장한다.
    UNIQUE (model_id, variant_name),

    FOREIGN KEY (model_id)
        REFERENCES vehicle_models(model_id)
);


/*
------------------------------------------------------------
4. defect_reports: 소비자 결함 신고

자동차 소유자가 접수한 신고 행을 저장한다.

중복 신고도 원본 기록이므로 삭제하지 않는다.
model_year는 신고 데이터에 있는 모델연도다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS defect_reports (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL,
    variant_id INTEGER,
    source_manufacturer_name TEXT,
    raw_model_name TEXT NOT NULL,
    received_date TEXT,
    model_year INTEGER,
    vehicle_type TEXT,
    source_file TEXT NOT NULL,

    FOREIGN KEY (model_id)
        REFERENCES vehicle_models(model_id),

    FOREIGN KEY (variant_id)
        REFERENCES vehicle_variants(variant_id)
);


/*
------------------------------------------------------------
5. recalls: 제작사 공식 리콜

생산기간과 리콜 개시일은 리콜 데이터의 날짜 정보다.
affected_count는 해당 리콜 기록의 대상 대수다.
여러 리콜 기록을 합한 값은 고유 차량 수와 다를 수 있다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS recalls (
    recall_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL,
    variant_id INTEGER,
    source_manufacturer_name TEXT,
    raw_model_name TEXT NOT NULL,
    production_start_date TEXT,
    production_end_date TEXT,
    recall_start_date TEXT,
    affected_count INTEGER,
    recall_reason TEXT,
    vehicle_type TEXT,
    source_file TEXT NOT NULL,

    FOREIGN KEY (model_id)
        REFERENCES vehicle_models(model_id),

    FOREIGN KEY (variant_id)
        REFERENCES vehicle_variants(variant_id)
);


/*
------------------------------------------------------------
6. faq_items: FAQ 질문과 답변

FAQ는 처음에 비어 있어도 된다.
나중에 INSERT문이나 별도 CSV로 내용을 추가한다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS faq_items (
    faq_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    source_url TEXT
);


/*
------------------------------------------------------------
7. data_coverage: 데이터 범위 안내

화면에서 "신고 데이터는 몇 년부터 몇 년까지인가?"를
안내할 때 사용할 수 있는 테이블이다.
------------------------------------------------------------
*/
CREATE TABLE IF NOT EXISTS data_coverage (
    coverage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    row_count INTEGER,
    note TEXT
);


/*
------------------------------------------------------------
8. 인덱스: 자주 사용하는 검색 조건을 빠르게 처리

제조사로 차종을 찾거나,
차종·모델연도로 신고를 찾거나,
차종·리콜개시일로 리콜을 정렬할 때 사용한다.
------------------------------------------------------------
*/
CREATE INDEX IF NOT EXISTS idx_models_manufacturer
    ON vehicle_models(manufacturer_id);

CREATE INDEX IF NOT EXISTS idx_variants_model
    ON vehicle_variants(model_id);

CREATE INDEX IF NOT EXISTS idx_defects_model_year
    ON defect_reports(model_id, model_year);

CREATE INDEX IF NOT EXISTS idx_recalls_model_date
    ON recalls(model_id, recall_start_date);


/*
------------------------------------------------------------
9. model_overview: 차종별 요약 화면용 VIEW

신고 데이터와 리콜 데이터를 먼저 각각 집계한 다음 합친다.
두 원본 테이블을 바로 JOIN하면 신고 행 수와 리콜 행 수가
서로 곱해져 숫자가 부풀 수 있기 때문이다.

이 VIEW는 Streamlit 화면의 요약 카드와 차종 비교에 사용한다.
------------------------------------------------------------
*/
CREATE VIEW IF NOT EXISTS model_overview AS
WITH defect_summary AS (
    SELECT
        model_id,
        COUNT(*) AS complaint_count,
        MAX(received_date) AS latest_report_date
    FROM defect_reports
    GROUP BY model_id
),
recall_summary AS (
    SELECT
        model_id,
        COUNT(*) AS recall_record_count,
        COALESCE(SUM(affected_count), 0) AS affected_count_sum,
        MAX(recall_start_date) AS latest_recall_date
    FROM recalls
    GROUP BY model_id
)
SELECT
    vm.model_id,
    m.manufacturer_name,
    vm.model_name,
    vm.vehicle_type,
    COALESCE(d.complaint_count, 0) AS complaint_count,
    COALESCE(d.latest_report_date, '') AS latest_report_date,
    COALESCE(r.recall_record_count, 0) AS recall_record_count,
    COALESCE(r.affected_count_sum, 0) AS affected_count_sum,
    COALESCE(r.latest_recall_date, '') AS latest_recall_date
FROM vehicle_models AS vm
JOIN manufacturers AS m
  ON m.manufacturer_id = vm.manufacturer_id
LEFT JOIN defect_summary AS d
  ON d.model_id = vm.model_id
LEFT JOIN recall_summary AS r
  ON r.model_id = vm.model_id;
