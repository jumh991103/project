"""전처리 CSV를 SQLite 데이터베이스로 만드는 실행 파일.

실행 위치:
    프로젝트 루트(project_t4_V2)에서 실행한다.

기본 실행:
    python scripts/build_database.py

이미 만들어진 DB를 새로 만들 때:
    python scripts/build_database.py --rebuild

이 파일이 하는 일:
    1. 전처리 CSV 두 개를 읽는다.
    2. schema.sql로 테이블을 만든다.
    3. CSV를 임시 stage 테이블에 저장한다.
    4. 제조사·대표 차종·세부 차명을 ID로 연결한다.
    5. 신고와 리콜 데이터를 최종 테이블에 저장한다.
    6. 행 수와 제조사 수를 출력해 결과를 확인한다.

신고 데이터의 중복 행은 원본 기록이므로 삭제하지 않는다.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------
# 프로젝트 경로
# ---------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "processed_data"
DATABASE_DIR = PROJECT_ROOT / "data" / "processed" / "database"
DATABASE_PATH = DATABASE_DIR / "recall_checker.sqlite3"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

DEFECT_FILE = "자동차제작결함신고정보_11개제조사_패밀리카.csv"
RECALL_FILE = "차종별리콜대수_11개제조사_패밀리카.csv"


# ---------------------------------------------------------
# 글자·숫자 정리 함수
# ---------------------------------------------------------
def clean_text(value: object) -> str:
    """빈칸과 불필요한 공백을 정리한다."""
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", text).strip()


def make_key(value: object) -> str:
    """제조사·차종을 연결할 때 사용하는 비교용 키를 만든다.

    화면에 보여줄 원래 이름은 바꾸지 않고,
    비교할 때만 공백과 하이픈을 제거한 키를 사용한다.

    이 규칙은 load_data.sql의 model_key 생성 규칙과 같다.
    """
    text = clean_text(value).casefold()
    return text.replace(" ", "").replace("-", "")


def to_int(value: object) -> int | None:
    """모델연도·리콜대수를 정수로 바꾼다."""
    text = clean_text(value).replace(",", "")
    if not text:
        return None

    try:
        return int(float(text))
    except ValueError:
        return None


def to_date(value: object) -> str | None:
    """날짜를 YYYY-MM-DD 형태로 통일한다."""
    text = clean_text(value)
    if not text:
        return None

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


# ---------------------------------------------------------
# CSV 읽기
# ---------------------------------------------------------
def read_csv_auto(path: Path) -> pd.DataFrame:
    """한글 CSV를 가능한 인코딩 순서대로 읽는다."""
    last_error: Exception | None = None

    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(
                path,
                encoding=encoding,
                dtype="string",
                keep_default_na=False,
            )
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error

    raise RuntimeError(f"CSV를 읽지 못했습니다: {path}") from last_error


def find_input_file(file_name: str) -> Path:
    """전처리 폴더에서 필요한 CSV를 찾는다."""
    path = INPUT_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"전처리 파일이 없습니다: {path}")
    return path


def validate_columns(
    frame: pd.DataFrame,
    required: set[str],
    file_name: str,
) -> None:
    """CSV에 필요한 열이 모두 있는지 확인한다."""
    missing = required.difference(frame.columns)
    if missing:
        raise KeyError(
            f"{file_name}에 필요한 열이 없습니다: {sorted(missing)}"
        )


# ---------------------------------------------------------
# stage 테이블과 기본 데이터 저장
# ---------------------------------------------------------
def create_stage_tables(connection: sqlite3.Connection) -> None:
    """CSV를 잠시 보관할 stage 테이블을 만든다."""
    connection.executescript(
        """
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
        """
    )


def insert_stage_data(
    connection: sqlite3.Connection,
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
) -> None:
    """전처리 CSV를 stage 테이블에 넣는다."""
    defect.to_sql("defect_stage", connection, if_exists="append", index=False)
    recalls.to_sql("recall_stage", connection, if_exists="append", index=False)


def load_manufacturers(
    connection: sqlite3.Connection,
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
) -> dict[str, int]:
    """두 CSV의 제조사를 모아 manufacturers에 저장한다."""
    names: dict[str, str] = {}

    for frame in (defect, recalls):
        for value in frame["manufacturer_name"]:
            name = clean_text(value)
            key = make_key(name)
            if key and key not in names:
                names[key] = name

    connection.executemany(
        """
        INSERT OR IGNORE INTO manufacturers
            (manufacturer_name, manufacturer_key)
        VALUES (?, ?)
        """,
        [(name, key) for key, name in names.items()],
    )

    return dict(
        connection.execute(
            "SELECT manufacturer_key, manufacturer_id FROM manufacturers"
        ).fetchall()
    )


def make_combined_models(
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, str]]:
    """두 CSV에 등장하는 대표 차종을 하나의 목록으로 만든다."""
    combined = pd.concat(
        [
            defect[["manufacturer_name", "model_name", "vehicle_type"]],
            recalls[["manufacturer_name", "model_name", "vehicle_type"]],
        ],
        ignore_index=True,
    )

    models: dict[tuple[str, str], dict[str, str]] = {}

    for row in combined.itertuples(index=False):
        manufacturer_name = clean_text(row.manufacturer_name)
        model_name = clean_text(row.model_name)
        manufacturer_key = make_key(manufacturer_name)
        model_key = make_key(model_name)

        if not manufacturer_key or not model_key:
            continue

        key = (manufacturer_key, model_key)
        if key not in models:
            models[key] = {
                "manufacturer_name": manufacturer_name,
                "model_name": model_name,
                "vehicle_type": clean_text(row.vehicle_type),
            }
        elif not models[key]["vehicle_type"]:
            models[key]["vehicle_type"] = clean_text(row.vehicle_type)

    return models


def load_models_and_variants(
    connection: sqlite3.Connection,
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
    manufacturer_ids: dict[str, int],
) -> tuple[dict[tuple[str, str], int], dict[tuple[int, str], int]]:
    """대표 차종과 원본 세부 차명을 저장하고 ID를 반환한다."""
    models = make_combined_models(defect, recalls)

    model_rows = []
    for (manufacturer_key, model_key), row in models.items():
        model_rows.append(
            (
                manufacturer_ids[manufacturer_key],
                row["model_name"],
                model_key,
                row["vehicle_type"] or None,
            )
        )

    connection.executemany(
        """
        INSERT OR IGNORE INTO vehicle_models
            (manufacturer_id, model_name, model_key, vehicle_type)
        VALUES (?, ?, ?, ?)
        """,
        model_rows,
    )

    model_ids = {
        (manufacturer_key, model_key): model_id
        for model_id, manufacturer_key, model_key in connection.execute(
            """
            SELECT
                vm.model_id,
                m.manufacturer_key,
                vm.model_key
            FROM vehicle_models vm
            JOIN manufacturers m
              ON m.manufacturer_id = vm.manufacturer_id
            """
        )
    }

    # 원본 차명은 대표 차종 아래의 세부 차명으로 저장한다.
    variant_names: set[tuple[str, str, str]] = set()
    for frame in (defect, recalls):
        for row in frame[["manufacturer_name", "model_name"]].itertuples(
            index=False
        ):
            manufacturer_key = make_key(row.manufacturer_name)
            model_name = clean_text(row.model_name)
            model_key = make_key(model_name)
            if manufacturer_key and model_key and model_name:
                variant_names.add((manufacturer_key, model_key, model_name))

    variant_rows = []
    for manufacturer_key, model_key, variant_name in sorted(variant_names):
        model_id = model_ids[(manufacturer_key, model_key)]
        variant_rows.append((model_id, variant_name, make_key(variant_name)))

    connection.executemany(
        """
        INSERT OR IGNORE INTO vehicle_variants
            (model_id, variant_name, variant_key)
        VALUES (?, ?, ?)
        """,
        variant_rows,
    )

    variant_ids = {
        (model_id, variant_name): variant_id
        for variant_id, model_id, variant_name in connection.execute(
            "SELECT variant_id, model_id, variant_name FROM vehicle_variants"
        )
    }

    return model_ids, variant_ids


def load_defect_reports(
    connection: sqlite3.Connection,
    defect: pd.DataFrame,
    model_ids: dict[tuple[str, str], int],
    variant_ids: dict[tuple[int, str], int],
) -> None:
    """소비자 신고 행을 최종 테이블에 저장한다."""
    rows = []
    unmatched = 0

    for row in defect.itertuples(index=False):
        manufacturer_name = clean_text(row.manufacturer_name)
        model_name = clean_text(row.model_name)
        model_id = model_ids.get((make_key(manufacturer_name), make_key(model_name)))

        if model_id is None:
            unmatched += 1
            continue

        rows.append(
            (
                model_id,
                variant_ids.get((model_id, model_name)),
                manufacturer_name,
                model_name,
                to_date(row.received_date),
                to_int(row.model_year),
                clean_text(row.vehicle_type) or None,
                DEFECT_FILE,
            )
        )

    if unmatched:
        raise ValueError(f"대표 차종에 연결되지 않은 신고 행: {unmatched}건")

    connection.executemany(
        """
        INSERT INTO defect_reports
            (model_id, variant_id, source_manufacturer_name, raw_model_name,
             received_date, model_year, vehicle_type, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def load_recalls(
    connection: sqlite3.Connection,
    recalls: pd.DataFrame,
    model_ids: dict[tuple[str, str], int],
    variant_ids: dict[tuple[int, str], int],
) -> None:
    """공식 리콜 행을 최종 테이블에 저장한다."""
    rows = []
    unmatched = 0

    for row in recalls.itertuples(index=False):
        manufacturer_name = clean_text(row.manufacturer_name)
        model_name = clean_text(row.model_name)
        model_id = model_ids.get((make_key(manufacturer_name), make_key(model_name)))

        if model_id is None:
            unmatched += 1
            continue

        rows.append(
            (
                model_id,
                variant_ids.get((model_id, model_name)),
                manufacturer_name,
                model_name,
                to_date(row.production_start_date),
                to_date(row.production_end_date),
                to_date(row.recall_start_date),
                to_int(row.affected_count),
                clean_text(row.recall_reason) or None,
                clean_text(row.vehicle_type) or None,
                RECALL_FILE,
            )
        )

    if unmatched:
        raise ValueError(f"대표 차종에 연결되지 않은 리콜 행: {unmatched}건")

    connection.executemany(
        """
        INSERT INTO recalls
            (model_id, variant_id, source_manufacturer_name, raw_model_name,
             production_start_date, production_end_date, recall_start_date,
             affected_count, recall_reason, vehicle_type, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def save_coverage(
    connection: sqlite3.Connection,
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
) -> None:
    """데이터 시작일·종료일·행 수를 기록한다."""
    defect_dates = pd.to_datetime(defect["received_date"], errors="coerce")
    recall_dates = pd.to_datetime(recalls["recall_start_date"], errors="coerce")

    rows = [
        (
            "defect_reports",
            defect_dates.min().strftime("%Y-%m-%d")
            if defect_dates.notna().any()
            else None,
            defect_dates.max().strftime("%Y-%m-%d")
            if defect_dates.notna().any()
            else None,
            len(defect),
            "접수일자 기준",
        ),
        (
            "recalls",
            recall_dates.min().strftime("%Y-%m-%d")
            if recall_dates.notna().any()
            else None,
            recall_dates.max().strftime("%Y-%m-%d")
            if recall_dates.notna().any()
            else None,
            len(recalls),
            "리콜개시일 기준",
        ),
    ]

    connection.executemany(
        """
        INSERT INTO data_coverage
            (dataset_name, start_date, end_date, row_count, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


# ---------------------------------------------------------
# 실행 함수
# ---------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="전처리 CSV로 SQLite 데이터베이스를 생성합니다."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="이미 있는 DB를 지우고 새로 생성합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    defect_path = find_input_file(DEFECT_FILE)
    recall_path = find_input_file(RECALL_FILE)

    defect = read_csv_auto(defect_path)
    recalls = read_csv_auto(recall_path)

    validate_columns(
        defect,
        {"received_date", "manufacturer_name", "model_name", "model_year", "vehicle_type"},
        DEFECT_FILE,
    )
    validate_columns(
        recalls,
        {
            "manufacturer_name",
            "model_name",
            "production_start_date",
            "production_end_date",
            "recall_start_date",
            "affected_count",
            "recall_reason",
            "vehicle_type",
        },
        RECALL_FILE,
    )

    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    if DATABASE_PATH.exists():
        if not args.rebuild:
            raise FileExistsError(
                f"DB가 이미 있습니다: {DATABASE_PATH}\n"
                "새로 만들려면 --rebuild 옵션을 사용하세요."
            )
        DATABASE_PATH.unlink()

    print("DB 생성을 시작합니다.")
    print(f"신고 CSV: {defect_path.name} ({len(defect):,}행)")
    print(f"리콜 CSV: {recall_path.name} ({len(recalls):,}행)")

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        # 1) schema.sql로 정식 테이블과 VIEW를 만든다.
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        # 2) CSV를 stage 테이블에 보관한다.
        create_stage_tables(connection)
        insert_stage_data(connection, defect, recalls)

        # 3) 제조사·차종·세부 차명 ID를 만든다.
        manufacturer_ids = load_manufacturers(connection, defect, recalls)
        model_ids, variant_ids = load_models_and_variants(
            connection, defect, recalls, manufacturer_ids
        )

        # 4) 신고·리콜 원본 행을 최종 테이블에 저장한다.
        load_defect_reports(connection, defect, model_ids, variant_ids)
        load_recalls(connection, recalls, model_ids, variant_ids)
        save_coverage(connection, defect, recalls)

        connection.commit()

        print("\nDB 생성 완료")
        print(f"DB 위치: {DATABASE_PATH}")

        for table in (
            "manufacturers",
            "vehicle_models",
            "vehicle_variants",
            "defect_reports",
            "recalls",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            print(f"{table}: {count:,}행")


if __name__ == "__main__":
    main()
