"""공개 사용 가능한 차량 사진을 찾아 assets/vehicles에 저장한다.

차량 사진은 Wikimedia Commons를 사용하는 공개 carapi 또는 Commons 검색에서
가져온다. 각 파일의 출처와 라이선스는 assets/vehicles/SOURCES.md에 기록한다.
BMW ML350처럼 제조사·차종 조합 자체가 이상한 행은 다른 제조사의 사진을
잘못 붙이지 않기 위해 이 스크립트에서 제외한다.
"""

from __future__ import annotations

import csv
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = PROJECT_ROOT / "assets" / "vehicles"
ALIAS_PATH = PROJECT_ROOT / "data" / "mappings" / "vehicle_image_aliases.csv"
SOURCES_PATH = IMAGE_DIR / "SOURCES.md"
USER_AGENT = "RecallChecker/1.0 (educational project)"

# 현재 DB에서 사진이 없는 차종을 기본 차종 단위로 조회한다.
# query_type이 commons인 항목은 Commons 검색 결과에서 정확한 모델명을 고른다.
IMAGE_QUERIES = [
    {"manufacturer": "KG 모빌리티", "pattern": "티볼리", "filename": "KG_모빌리티_티볼리.jpg", "make": "KGM", "model": "Tivoli", "query_type": "carapi"},
    {"manufacturer": "기아", "pattern": "모하비", "filename": "기아_모하비.jpg", "make": "Kia", "model": "Mohave", "query_type": "carapi"},
    {"manufacturer": "기아", "pattern": "카렌스", "filename": "기아_카렌스.jpg", "make": "Kia", "model": "Carens", "query_type": "carapi"},
    {"manufacturer": "르노코리아", "pattern": "CAPTUR", "filename": "르노코리아_CAPTUR.jpg", "make": "Renault", "model": "Captur", "query_type": "commons"},
    {"manufacturer": "르노코리아", "pattern": "KOLEOS", "filename": "르노코리아_KOLEOS_대표.jpg", "make": "Renault", "model": "Koleos", "query_type": "carapi"},
    # QM3는 르노삼성의 국내 차명이라 Commons 검색은 Samsung으로 하는 편이 정확하다.
    {"manufacturer": "르노코리아", "pattern": "QM3", "filename": "르노코리아_QM3.jpg", "make": "Samsung", "model": "QM3", "query_type": "commons"},
    {"manufacturer": "르노코리아", "pattern": "QM5", "filename": "르노코리아_QM5.jpg", "make": "Renault", "model": "QM5", "query_type": "carapi"},
    {"manufacturer": "르노코리아", "pattern": "XM3", "filename": "르노코리아_XM3.jpg", "make": "Renault Samsung", "model": "XM3", "query_type": "commons"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "GLK", "filename": "메르세데스_벤츠_GLK.jpg", "make": "Mercedes-Benz", "model": "GLK", "query_type": "carapi"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "ML", "filename": "메르세데스_벤츠_ML.jpg", "make": "Mercedes-Benz", "model": "ML", "query_type": "carapi"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "EQA", "filename": "메르세데스_벤츠_EQA.jpg", "make": "Mercedes-Benz", "model": "EQA", "query_type": "carapi"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "EQB", "filename": "메르세데스_벤츠_EQB.jpg", "make": "Mercedes-Benz", "model": "EQB", "query_type": "carapi"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "GLB", "filename": "메르세데스_벤츠_GLB.jpg", "make": "Mercedes-Benz", "model": "GLB", "query_type": "commons"},
    {"manufacturer": "메르세데스 벤츠", "pattern": "GLE", "filename": "메르세데스_벤츠_GLE.jpg", "make": "Mercedes-Benz", "model": "GLE", "query_type": "carapi"},
    {"manufacturer": "재규어랜드로버", "pattern": "E-PACE", "filename": "재규어랜드로버_재규어_E-PACE.jpg", "make": "Jaguar", "model": "E-Pace", "query_type": "carapi"},
    {"manufacturer": "재규어랜드로버", "pattern": "프리랜더", "filename": "재규어랜드로버_랜드로버_프리랜더.jpg", "make": "Land Rover", "model": "Freelander", "query_type": "carapi"},
    {"manufacturer": "토요타", "pattern": "RX500h", "filename": "토요타_렉서스_RX500h.jpg", "make": "Lexus", "model": "RX", "query_type": "carapi"},
    {"manufacturer": "토요타", "pattern": "Alphard", "filename": "토요타_Alphard.jpg", "make": "Toyota", "model": "Alphard", "query_type": "commons"},
    {"manufacturer": "현대자동차", "pattern": "GV70", "filename": "현대자동차_GV70.jpg", "make": "Genesis", "model": "GV70", "query_type": "carapi"},
    {"manufacturer": "현대자동차", "pattern": "GV80", "filename": "현대자동차_GV80.jpg", "make": "Genesis", "model": "GV80", "query_type": "carapi"},
    {"manufacturer": "현대자동차", "pattern": "그랜드 스타렉스", "filename": "현대자동차_그랜드_스타렉스.jpg", "make": "Hyundai", "model": "Grand Starex", "query_type": "carapi"},
]


def clean_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


def download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def clean_metadata(value: str | None) -> str:
    if not value:
        return "-"
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def carapi_image(item: dict) -> tuple[bytes, str, str, str]:
    params = urlencode({"make": item["make"], "model": item["model"], "format": "json"})
    metadata_url = f"https://carapi.trustcar.info/getImage?{params}"
    metadata = request_json(metadata_url)
    if not metadata.get("found"):
        raise RuntimeError(f"carapi에서 사진을 찾지 못했습니다: {item['make']} {item['model']}")

    image_url = f"https://carapi.trustcar.info/getImage?{urlencode({'make': item['make'], 'model': item['model']})}"
    return (
        download_bytes(image_url),
        metadata.get("title", f"{item['make']} {item['model']}"),
        metadata.get("license", "-"),
        metadata.get("attribution", "-") + f" (metadata: {metadata_url})",
    )


def commons_image(item: dict) -> tuple[bytes, str, str, str]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{item['make']} {item['model']}",
        "gsrnamespace": "6",
        "gsrlimit": "50",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1200",
    }
    api_url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    data = request_json(api_url)
    pages = list(data.get("query", {}).get("pages", {}).values())
    expected = clean_key(item["model"])
    chosen = None
    for page in pages:
        title_key = clean_key(page.get("title", ""))
        if expected and expected in title_key:
            chosen = page
            break
    if chosen is None and pages:
        chosen = pages[0]
    if chosen is None:
        raise RuntimeError(f"Commons에서 사진을 찾지 못했습니다: {item['make']} {item['model']}")

    info = chosen.get("imageinfo", [{}])[0]
    thumb_url = info.get("thumburl") or info.get("url")
    if not thumb_url:
        raise RuntimeError(f"Commons 이미지 URL이 없습니다: {chosen.get('title')}")
    metadata = info.get("extmetadata", {})
    title = chosen.get("title", "").removeprefix("File:")
    source_page = info.get("descriptionurl", f"https://commons.wikimedia.org/wiki/{quote(chosen.get('title', ''))}")
    license_name = clean_metadata(metadata.get("LicenseShortName", {}).get("value"))
    artist = clean_metadata(metadata.get("Artist", {}).get("value"))
    attribution = f"{title} — {artist} ({license_name}), via Wikimedia Commons"
    return download_bytes(thumb_url), title, license_name, f"{attribution} (source: {source_page})"


def append_aliases() -> None:
    with ALIAS_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    existing = {(clean_key(row["manufacturer_name"]), clean_key(row["model_pattern"])) for row in rows}
    for item in IMAGE_QUERIES:
        key = (clean_key(item["manufacturer"]), clean_key(item["pattern"]))
        if key not in existing:
            rows.append(
                {
                    "manufacturer_name": item["manufacturer"],
                    "model_pattern": item["pattern"],
                    "image_filename": item["filename"],
                }
            )
    with ALIAS_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["manufacturer_name", "model_pattern", "image_filename"])
        writer.writeheader()
        writer.writerows(rows)


def append_sources(source_rows: list[tuple[str, str, str, str]]) -> None:
    existing_text = SOURCES_PATH.read_text(encoding="utf-8")
    # 같은 파일을 다시 내려받았을 때 이전 출처 행을 새 정보로 교체한다.
    source_filenames = {filename for filename, _, _, _ in source_rows}
    kept_lines = [
        line
        for line in existing_text.splitlines()
        if not any(f"`{filename}`" in line for filename in source_filenames)
    ]
    additions = [
        f"| `{filename}` | {model} | {title} / {license_info} |"
        for filename, model, title, license_info in source_rows
    ]
    if additions:
        SOURCES_PATH.write_text("\n".join(kept_lines).rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    source_rows = []
    for item in IMAGE_QUERIES:
        output_path = IMAGE_DIR / item["filename"]
        try:
            if item["query_type"] == "carapi":
                data, title, license_name, attribution = carapi_image(item)
            else:
                data, title, license_name, attribution = commons_image(item)
            output_path.write_bytes(data)
            source_rows.append((item["filename"], f"{item['manufacturer']} {item['pattern']}", title, attribution))
            print(f"저장 완료: {output_path.name} ({len(data):,} bytes)")
        except Exception as error:
            print(f"건너뜀: {item['manufacturer']} {item['pattern']} -> {error}")

    append_aliases()
    append_sources(source_rows)
    print(f"사진 폴더: {IMAGE_DIR}")
    print(f"매핑표: {ALIAS_PATH}")
    print(f"출처 기록: {SOURCES_PATH}")


if __name__ == "__main__":
    main()
