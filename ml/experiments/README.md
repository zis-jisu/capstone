# 최종 역할 가중 R-GAE 실험

이 폴더는 **2026-10-01 그래프 학습 → 2026-10-07 그래프 평가**의 시간 이동 1-hop 실험을 보존합니다. [최종 노트북](rgae_temporal_1hop_multi_handoff_final.ipynb)은 저장된 결과를 읽고, [실험 스크립트](rgae_final_no_leakage_experiment.py)는 `data/`의 두 그래프로 역할 가중치 선택과 평가 결과를 다시 생성합니다. 운영 API 구현은 상위 `rgae_service/`에 있습니다.

역할 edge 계수는 APPROVER 31, OWNER 27, REVIEWER 21, COLLABORATOR 17, RELATED 4입니다. 최종 우선순위 산식은 구조 55 + 마감 30 + 연속성 15 − RELATED-only 10입니다. 운영 GT는 계수 선택에 사용하지 않고 최종 평가에만 사용했습니다.

| 김지수 1-hop, K=5 | Precision@5 | nDCG@5 |
| --- | ---: | ---: |
| 비가중 R-GAE | 0.60 | 0.640 |
| 역할 가중 R-GAE | 1.00 | 0.786 |
| 역할 가중 R-GAE + 최종 산식 | 1.00 | 0.845 |

수치는 [`results/final_1hop_2hop_metrics.csv`](results/final_1hop_2hop_metrics.csv)에 저장돼 있습니다. 김지수+박보검 → 원이정 다중 인수인계 실험의 GT에는 박보검 업무의 **proxy GT**가 포함돼 있으므로 독립 human GT 성능으로 해석하지 않습니다. 근거와 한계는 [결과 보고서](results/rgae_temporal_1hop_results_report.md)에 적었습니다.

## 재현

`ml/`에서 별도 실험 의존성을 설치한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r experiments/requirements.txt
.\.venv\Scripts\python.exe experiments/rgae_final_no_leakage_experiment.py
```

스크립트는 `experiments/results/`의 CSV·설정 JSON을 다시 생성합니다. 노트북은 해당 결과를 읽으며, 첫 코드 셀의 `RUN_TRAINING=True`를 설정하면 재학습을 실행합니다.
