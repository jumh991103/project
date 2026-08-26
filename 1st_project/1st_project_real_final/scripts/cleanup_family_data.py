"""패밀리카 전처리 결과에서 조회에 필요 없는 대표 차종을 정리한다.

정리 기준:
1. 어린이·통학·보호차·구급차·특수차·밴 등 특수 용도 표기 제외
2. 차종명에 '구형'이 들어간 차종 제외
3. 소비자 신고 데이터에 유효한 모델연도가 한 건도 없는 제조사·차종 조합 제외

기본 실행은 제거 예정 건수만 출력한다.
실제 CSV를 덮어쓰려면 다음처럼 실행한다.

    python scripts/cleanup_family_data.py --apply

원본 CSV는 data/raw에 있으므로 변경하지 않는다.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "processed_data"


def read_csv_auto(path: Path) -> pd.DataFrame:
    """한글 CSV를 가능한 인코딩 순서대로 읽는다."""
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype="string")
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise RuntimeError(f"CSV를 읽지 못했습니다: {path}")


def find_csv(keyword: str) -> Path:
    """전처리 폴더에서 키워드가 들어간 CSV를 찾는다."""
    files = sorted(path for path in INPUT_DIR.glob("*.csv") if keyword in path.stem)
    if not files:
        raise FileNotFoundError(f"파일을 찾지 못했습니다: {keyword}")
    return files[0]


def clean_key(value: object) -> str:
    """제조사·차종 조합 비교용 키를 만든다.

    build_database.py의 연결 규칙과 같게 공백·하이픈만 제거한다.
    괄호나 트림 표기를 여기서 지우면 DB에서 다른 대표 차종으로
    나뉠 수 있으므로 임의로 더 삭제하지 않는다.
    """
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace(" ", "").replace("-", "")


# 패밀리카 범위에서 제외할 특수·상용 용도 표기
EXCLUDE_MODEL_PATTERNS = re.compile(
    r"어린이|통학|보호차|school\s*bus|구급|앰뷸런스|ambulance|특수|휠체어|wheelchair|"
    r"밴|van|캠핑카|캠핑|리무진|limousine|왜건|트랙터|tractor|FH\s*6x4",
    flags=re.IGNORECASE,
)

CANONICAL_STAREX_KEYS = {
    "그랜드스타렉스(grandstarex)",
    "스타렉스(starex)",
}

# 현대 팰리세이드는 괄호가 붙은 표기를 대표 표기로 사용한다.
# 단독으로 적힌 "팰리세이드" 행은 같은 차종의 중복 표기이므로 제외한다.
PALLISADE_DUPLICATE_NAMES = {"팰리세이드", "palisade"}


def is_excluded_model(value: object) -> bool:
    """특수 용도 또는 대표 차종으로 보기 어려운 세부 차명인지 확인한다."""
    text = "" if value is None or pd.isna(value) else str(value)
    if text.strip().casefold() in PALLISADE_DUPLICATE_NAMES:
        return True
    if EXCLUDE_MODEL_PATTERNS.search(text):
        return True

    # 스타렉스는 대표 표기 2개만 남기고 나머지 세부 표기를 정리한다.
    if "스타렉스" in text or "starex" in text.casefold():
        return clean_key(text) not in CANONICAL_STAREX_KEYS
    return False


def mercedes_family(value: object) -> str:
    """메르세데스 차종을 GLA·GLB·GLC 같은 계열명으로 묶는다."""
    text = "" if value is None or pd.isna(value) else str(value)
    # GLC350처럼 계열명 바로 뒤에 숫자가 붙는 표기가 많아 \b를 쓰지 않는다.
    match = re.search(r"(EQA|EQB|EQC|GLA|GLB|GLC|GLE|GLK|GLS|ML)", text, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def build_keep_mask(
    defect: pd.DataFrame,
    recalls: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """신고·리콜 데이터에 적용할 유지 마스크와 제거 사유표를 만든다."""
    defect_manufacturer_key = defect["manufacturer_name"].map(clean_key)
    defect_model_key = defect["model_name"].map(clean_key)
    recall_manufacturer_key = recalls["manufacturer_name"].map(clean_key)
    recall_model_key = recalls["model_name"].map(clean_key)

    model_year = pd.to_numeric(defect["model_year"], errors="coerce")
    valid_year_pair = model_year.notna() & model_year.gt(0)
    valid_pairs = set(
        zip(
            defect_manufacturer_key[valid_year_pair],
            defect_model_key[valid_year_pair],
        )
    )

    defect_special = defect["model_name"].map(is_excluded_model)
    recall_special = recalls["model_name"].map(is_excluded_model)
    defect_old = defect["model_name"].fillna("").str.contains("구형", case=False, regex=False)
    recall_old = recalls["model_name"].fillna("").str.contains("구형", case=False, regex=False)

    defect_has_year = pd.Series(
        list(zip(defect_manufacturer_key, defect_model_key)), index=defect.index
    ).isin(valid_pairs)
    recall_has_year = pd.Series(
        list(zip(recall_manufacturer_key, recall_model_key)), index=recalls.index
    ).isin(valid_pairs)

    defect_keep = ~(defect_special | defect_old) & defect_has_year
    recall_keep = ~(recall_special | recall_old) & recall_has_year

    # 메르세데스는 세부 트림이 지나치게 많아 대표 계열별 신고가 가장 많은
    # 차종 하나만 남긴다. 신고 4건 이하는 조회 목록에서 제외한다.
    mercedes_key = clean_key("메르세데스 벤츠")
    defect_pair = list(zip(defect_manufacturer_key, defect_model_key))
    defect_counts = pd.Series(defect_pair).value_counts()
    mercedes_candidates: list[tuple[str, str, int, str]] = []
    for pair, count in defect_counts.items():
        manufacturer_key, model_key = pair
        if manufacturer_key != mercedes_key or int(count) < 5:
            continue
        model_values = defect.loc[
            (defect_manufacturer_key == manufacturer_key)
            & (defect_model_key == model_key),
            "model_name",
        ]
        model_name = str(model_values.iloc[0]) if not model_values.empty else ""
        mercedes_candidates.append(
            (manufacturer_key, model_key, int(count), mercedes_family(model_name))
        )

    keep_mercedes_pairs: set[tuple[str, str]] = set()
    grouped_candidates: dict[str, list[tuple[str, str, int, str]]] = {}
    for candidate in mercedes_candidates:
        if candidate[3]:
            grouped_candidates.setdefault(candidate[3], []).append(candidate)
    for family_candidates in grouped_candidates.values():
        best = max(family_candidates, key=lambda item: (item[2], item[1]))
        keep_mercedes_pairs.add((best[0], best[1]))

    for index, (manufacturer_key, model_key) in enumerate(defect_pair):
        if manufacturer_key == mercedes_key and (manufacturer_key, model_key) not in keep_mercedes_pairs:
            defect_keep.iloc[index] = False
    for index, pair in enumerate(zip(recall_manufacturer_key, recall_model_key)):
        if pair[0] == mercedes_key and pair not in keep_mercedes_pairs:
            recall_keep.iloc[index] = False

    reason_rows = []
    for frame, special, old, has_year, label in (
        (defect, defect_special, defect_old, defect_has_year, "신고"),
        (recalls, recall_special, recall_old, recall_has_year, "리콜"),
    ):
        temp = frame[["manufacturer_name", "model_name"]].copy()
        temp["dataset"] = label
        temp["reason"] = ""
        temp.loc[special, "reason"] = "특수·상용 용도 표기"
        temp.loc[~special & old, "reason"] = "구형 차종 표기"
        temp.loc[~special & ~old & ~has_year, "reason"] = "모델연도 없음"
        if label == "신고":
            temp_manufacturer_key = temp["manufacturer_name"].map(clean_key)
            temp_model_key = temp["model_name"].map(clean_key)
            temp.loc[
                (temp_manufacturer_key == mercedes_key)
                & ~temp.index.to_series().map(defect_keep),
                "reason",
            ] = "메르세데스 유사·신고 적은 차종"
        reason_rows.append(temp[temp["reason"] != ""])

    return defect_keep, recall_keep, pd.concat(reason_rows, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="패밀리카 전처리 결과를 정리합니다.")
    parser.add_argument("--apply", action="store_true", help="정리 결과를 CSV에 저장합니다.")
    args = parser.parse_args()

    defect_path = find_csv("자동차제작결함신고정보")
    recall_path = find_csv("차종별리콜대수")
    defect = read_csv_auto(defect_path)
    recalls = read_csv_auto(recall_path)

    defect_keep, recall_keep, reasons = build_keep_mask(defect, recalls)

    print("=== 정리 예정 결과 ===")
    print(f"신고: {len(defect):,}행 → {int(defect_keep.sum()):,}행 (제거 {int((~defect_keep).sum()):,}행)")
    print(f"리콜: {len(recalls):,}행 → {int(recall_keep.sum()):,}행 (제거 {int((~recall_keep).sum()):,}행)")
    print("제거 사유별 행 수:")
    print(reasons.groupby(["dataset", "reason"]).size().to_string())
    print("\n대표 차종 제거 목록(상위 50개):")
    print(
        reasons[["manufacturer_name", "model_name"]]
        .drop_duplicates()
        .sort_values(["manufacturer_name", "model_name"])
        .head(50)
        .to_string(index=False)
    )

    if not args.apply:
        print("\n미리보기만 했습니다. 반영하려면 --apply를 붙여 실행하세요.")
        return

    defect.loc[defect_keep].to_csv(defect_path, index=False, encoding="utf-8-sig")
    recalls.loc[recall_keep].to_csv(recall_path, index=False, encoding="utf-8-sig")
    print("\n정리 완료:", defect_path)
    print("정리 완료:", recall_path)


if __name__ == "__main__":
    main()
