# SKN36-1st-4team

패밀리카를 구매하기 전에 차종별 리콜 이력과 결함 신고 내용을 확인하는 프로젝트.

작업 순서:

1. CSV 파일 확인
2. 제조사와 차종명 정리
3. 전처리 결과 저장
4. SQLite 테이블 생성
5. SQL 조회 확인
6. Streamlit 화면 연결

원본 데이터는 `data/raw`에 보관.

전처리 결과는 `data/processed/processed_data`에 저장.

전처리는 `notebooks` 폴더의 Jupyter Notebook에서 단계별로 진행.
