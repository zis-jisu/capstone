# 그래프 데이터와 스크립트

이 폴더는 합성 데이터로 그래프를 생성하고 검토할 때 사용한 스크립트와 예시 JSON을 모아 둡니다. 스크립트의 입력·출력 경로는 현재 작업 디렉터리를 기준으로 하므로 이 폴더에서 실행합니다.

```bash
cd graph
python analyze_synthetic.py
python export_graph.py
```

`import_synthetic.py`는 Supabase에 데이터를 쓰므로 실행 전에 환경변수와 대상 프로젝트를 확인하세요. `sql/`의 SQL은 데모 데이터용입니다.
