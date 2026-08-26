# DB 설계 노트 — "모델연도 ↔ 생산기간"을 직접 JOIN하지 않은 이유

패밀리카 리콜·결함신고 통합조회 서비스(리콜체크) — `sql/schema.sql`의
`model_overview` VIEW 설계 근거 정리. 포트폴리오 작성 시 참고용.

관련 파일: `sql/schema.sql` (200~247행), `app/streamlit_app.py`(차종 비교 화면 안내 문구)

---

## 문제 상황

두 원본 데이터가 "언제"를 서로 다른 방식으로 기록한다.

- **소비자 결함신고 데이터**: `model_year`(모델연식) 컬럼 하나만 있음 — 예: "2020년형"
- **공식 리콜 데이터**: `production_start_date` ~ `production_end_date`(생산기간) 범위로 기록 — 예: "2019-08-01 ~ 2020-05-10"

자동차는 실제 생산을 전년도 후반부터 시작해서 "OO년형"으로 출시하는 경우가 흔하다.
그래서 **"모델연식 2020 = 생산기간에 2020년이 포함된 차"라고 날짜 기준으로 직접
이어붙이면 틀린 매칭이 자주 생긴다.**

또한 두 원본 테이블(`defect_reports`, `recalls`)을 집계 없이 바로 JOIN하면
신고 행 수와 리콜 행 수가 서로 곱해져 결과가 부풀어버리는 문제(카티션 곱)도 있다.
예: 한 차종에 신고 10건, 리콜 5건이 있으면 무작정 JOIN 시 10 × 5 = 50행처럼
계산될 수 있음.

---

## 해결 방향: 날짜가 아니라 `model_id`로만 연결한다

두 데이터를 날짜로 억지로 잇지 않고, **"같은 차종(`model_id`)"이라는 공통 축으로만
연결**한다.

```text
manufacturers
      ↓
vehicle_models (model_id)
   ↙            ↘
defect_reports        recalls
  model_year          production_start_date
  received_date       production_end_date
      ↓                    ↓
  신고수 집계          리콜건수·리콜대수 집계
        ↘              ↙
         model_id 기준 LEFT JOIN
                ↓
           차종별 비교 결과
```

절차:

1. 신고 테이블은 신고 테이블끼리 `model_id`별로 먼저 집계한다 (몇 건인지)
2. 리콜 테이블은 리콜 테이블끼리 `model_id`별로 먼저 집계한다 (몇 건 / 몇 대인지)
3. 각각 집계를 끝낸 다음, 마지막에 `model_id` 기준으로 딱 한 번만 `LEFT JOIN`한다

집계를 먼저 하고 나중에 합치는 이유가 바로 앞서 말한 카티션 곱 문제를 막기 위해서다.

---

## 실제 구현: `sql/schema.sql`의 `model_overview` VIEW

```sql
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
```

스키마 주석에도 이유가 명시돼 있다.

> 신고 데이터와 리콜 데이터를 먼저 각각 집계한 다음 합친다.
> 두 원본 테이블을 바로 JOIN하면 신고 행 수와 리콜 행 수가
> 서로 곱해져 숫자가 부풀 수 있기 때문이다.

---

## "리콜건수"와 "리콜대수"를 헷갈리지 않게 컬럼을 분리

- `recall_record_count` — 리콜 조치(캠페인)가 몇 번 있었는가
- `affected_count_sum` — 그 리콜 대상 차량이 총 몇 대인가

이 둘을 하나로 뭉뚱그려 "리콜수"라고만 부르면 "리콜 5건"인지 "리콜 대상 5,000대"인지
헷갈리기 때문에 DB 컬럼 단계부터 분리해뒀다.

---

## 화면(Streamlit)에서의 반영

`app/streamlit_app.py`의 차종 비교 화면에는 이 설계를 사용자에게도 그대로 안내한다.

> "모델연도는 소유자 신고 건수에 적용됩니다. 공식 리콜은 생산기간 기준이라
> 선택한 모델연도로 억지로 나누지 않고 차종 전체 리콜을 보여줍니다."

즉 사용자가 특정 연식을 선택해도:
- 소유자 신고 건수는 그 연식으로 필터링해서 보여주고
- 공식 리콜은 (생산기간 기준이라 연식과 1:1 대응이 안 되므로) 차종 전체 리콜을 그대로 보여준다

---

## 연식별로 리콜까지 정확히 맞추고 싶다면? (현재는 미구현)

정말 "2020년형 리콜만" 보고 싶다면, 실제 근거로 리콜이 어느 연식에 해당하는지
확인된 경우에만 매핑하는 중간 테이블을 추가로 둘 수 있다.

```text
recall_model_year_map
─────────────────────
recall_id
model_year
match_type   -- 예: confirmed(확인됨) 등
```

이렇게 하면:

```text
defect_reports.model_year
        ↓
   vehicle_models + model_year
        ↑
recall_model_year_map
        ↑
     recalls
```

로 연식별 비교도 가능해지지만, **근거 없이 날짜만 보고 추정 매핑하면 다시 원래
문제(부정확한 매칭)로 돌아가므로**, 실제 근거가 확인된 리콜만 넣는 것이 전제다.
현재 프로젝트에는 이 테이블이 없고, 위에서 설명한 "차종 기준 집계 + 각자의
시간정보를 있는 그대로 보여주는" 방식만 구현돼 있다.

---

## 포트폴리오 작성 시 활용 포인트

- **설계 판단의 근거**: 서로 다른 시간 기준(연식 vs 생산기간)을 가진 두 공공데이터를
  다룰 때, 억지로 정확도를 흉내내는 매칭보다 **각 데이터의 원래 의미를 보존하는 설계**를
  선택한 이유를 설명할 수 있음
- **성능/정합성 문제 예방**: 집계 없이 바로 JOIN했을 때 생기는 카티션 곱 문제를
  사전에 인지하고 `WITH ... GROUP BY` → `LEFT JOIN` 순서로 설계
- **용어 정의의 중요성**: "리콜건수"와 "리콜대수"처럼 비슷해 보이지만 다른 의미의
  지표를 컬럼 단계에서부터 명확히 분리
- **확장 여지를 남긴 설계**: 연식별 정밀 매칭이 필요해지면 `recall_model_year_map`
  같은 근거 기반 매핑 테이블을 추가하는 식으로 확장 가능하다는 점까지 고려함

---

*이 문서는 2026-08-25 기준 `sql/schema.sql`, `app/streamlit_app.py` 실제 코드를
직접 확인해 작성했습니다.*
