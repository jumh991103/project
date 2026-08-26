"""현재 SQLite의 차종 목록을 사람이 정한 기준으로 정리한다.

빨간색으로 표시한 차종은 조회 목록과 관련 기록에서 제거하고,
노란색으로 표시한 차종은 대표 model_id 하나로 합친다.

실행 전 같은 폴더에 백업 DB를 자동으로 만든다.
실행:
    python scripts/apply_model_cleanup.py
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "processed" / "database" / "recall_checker.sqlite3"

# 이미지에서 빨간색으로 표시된 삭제 대상
DELETE_MODELS = [
    ("기아", "봉고 프런티어 GLS"),
    ("현대자동차", "스타렉스(STAREX)"),
]

# (제조사, 현재 DB에 있는 대표 행, 최종 화면 표시명, 합칠 차종들)
MERGE_GROUPS = [
    ("기아", "카렌스", "카렌스", ["카렌스II", "카렌스베타2.0"]),
    ("르노코리아", "KOLEOS(콜레오스)", "KOLEOS", ["KOLEOS Hybrid(콜레오스 하이브리드)"]),
    ("르노코리아", "XM3", "XM3", ["XM3 하이브리드"]),
    ("재규어랜드로버", "재규어 E-PACE D180", "재규어 E-PACE", ["재규어 E-PACE P250"]),
]


def model_key(value: str) -> str:
    """DB의 차종 비교용 키와 같은 방식으로 만든다."""
    text = str(value).casefold().strip()
    text = re.sub(r"\s+", "", text)
    return text.replace("-", "")


def find_model_id(connection: sqlite3.Connection, manufacturer: str, model: str) -> int:
    row = connection.execute(
        """
        SELECT vm.model_id
        FROM vehicle_models AS vm
        JOIN manufacturers AS m ON m.manufacturer_id = vm.manufacturer_id
        WHERE m.manufacturer_name = ? AND vm.model_name = ?
        """,
        (manufacturer, model),
    ).fetchone()
    if row is None:
        raise ValueError(f"DB에서 차종을 찾지 못했습니다: {manufacturer} / {model}")
    return int(row[0])


def merge_model(
    connection: sqlite3.Connection,
    manufacturer: str,
    target_lookup_name: str,
    canonical_name: str,
    source_names: list[str],
) -> None:
    """source 차종의 신고·리콜·세부 차명을 대표 차종으로 이동한다."""
    target_id = find_model_id(connection, manufacturer, target_lookup_name)

    for source_name in source_names:
        # 대표 차종 이름을 source 목록에 적은 경우는 이미 대표이므로 건너뛴다.
        if source_name == target_lookup_name:
            continue

        source_id = find_model_id(connection, manufacturer, source_name)

        # 같은 이름의 세부 차명이 대표 차종에 이미 있으면 그 variant_id를 사용한다.
        target_variants = {
            name: variant_id
            for variant_id, name in connection.execute(
                "SELECT variant_id, variant_name FROM vehicle_variants WHERE model_id = ?",
                (target_id,),
            )
        }
        source_variants = connection.execute(
            "SELECT variant_id, variant_name FROM vehicle_variants WHERE model_id = ?",
            (source_id,),
        ).fetchall()

        for variant_id, variant_name in source_variants:
            if variant_name in target_variants:
                existing_id = target_variants[variant_name]
                connection.execute(
                    "UPDATE defect_reports SET variant_id = ? WHERE variant_id = ?",
                    (existing_id, variant_id),
                )
                connection.execute(
                    "UPDATE recalls SET variant_id = ? WHERE variant_id = ?",
                    (existing_id, variant_id),
                )
                connection.execute(
                    "DELETE FROM vehicle_variants WHERE variant_id = ?",
                    (variant_id,),
                )
            else:
                connection.execute(
                    "UPDATE vehicle_variants SET model_id = ? WHERE variant_id = ?",
                    (target_id, variant_id),
                )

        connection.execute(
            "UPDATE defect_reports SET model_id = ? WHERE model_id = ?",
            (target_id, source_id),
        )
        connection.execute(
            "UPDATE recalls SET model_id = ? WHERE model_id = ?",
            (target_id, source_id),
        )
        connection.execute("DELETE FROM vehicle_models WHERE model_id = ?", (source_id,))

    # 화면에는 트림·연료 표기를 뺀 대표 이름만 보여준다.
    manufacturer_id = connection.execute(
        "SELECT manufacturer_id FROM manufacturers WHERE manufacturer_name = ?",
        (manufacturer,),
    ).fetchone()[0]
    connection.execute(
        """
        UPDATE vehicle_models
        SET model_name = ?, model_key = ?
        WHERE model_id = ? AND manufacturer_id = ?
        """,
        (canonical_name, model_key(canonical_name), target_id, manufacturer_id),
    )


def delete_model(connection: sqlite3.Connection, manufacturer: str, model: str) -> None:
    model_id = find_model_id(connection, manufacturer, model)

    # 외래키가 연결된 기록부터 지운 뒤 차종과 세부 차명을 지운다.
    connection.execute("DELETE FROM defect_reports WHERE model_id = ?", (model_id,))
    connection.execute("DELETE FROM recalls WHERE model_id = ?", (model_id,))
    connection.execute("DELETE FROM vehicle_variants WHERE model_id = ?", (model_id,))
    connection.execute("DELETE FROM vehicle_models WHERE model_id = ?", (model_id,))


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB 파일을 찾지 못했습니다: {DB_PATH}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_name(f"{DB_PATH.stem}_before_model_cleanup_{timestamp}{DB_PATH.suffix}")
    shutil.copy2(DB_PATH, backup_path)

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            for manufacturer, target_lookup_name, canonical_name, source_names in MERGE_GROUPS:
                merge_model(
                    connection,
                    manufacturer,
                    target_lookup_name,
                    canonical_name,
                    source_names,
                )
            for manufacturer, model in DELETE_MODELS:
                delete_model(connection, manufacturer, model)
    except Exception:
        connection.close()
        raise
    connection.close()

    print(f"차종 정리 완료: {DB_PATH}")
    print(f"백업 파일: {backup_path}")
    print("삭제:", ", ".join(f"{m} / {n}" for m, n in DELETE_MODELS))
    print("통합:", ", ".join(f"{m} / {display}" for m, _, display, _ in MERGE_GROUPS))


if __name__ == "__main__":
    main()
