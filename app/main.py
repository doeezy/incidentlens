import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.database import init_db

# TODO: /answers 요청에 project_name 추가
# - 사용자가 선택한 프로젝트 범위에서만 incident 검색
# - project_name 없으면 프로젝트 선택 안내

# TODO: 최근 프로젝트 목록 API 추가
# - GET /api/v1/projects/recent
# - incident_count, last_seen_at 기준 정렬

# TODO: 간단한 웹 UI 구현
# - 프로젝트 선택
# - 질문 입력
# - 답변 출력
# - Retrieved Incident / Evidence 표시

# TODO: Agent Trace 추가
# - LangGraph node 실행 순서 기록
# - retrieve_incidents / generate_answer elapsed_ms 저장
# - 추후 confidence_judge, query_analyzer 노드 추가 시 trace 확장
# - 추후 UI에서 실행 과정 표시

# TODO: 답변 품질 개선
# - 의도 판단: 사용자 질문 요청시 먼저 질문에 대한 의도 파악 후 처리
# - 답변 구조: 가능 원인 / 근거 / 해결 이력 / 확인해볼 것
# - 근거 부족 시 명확히 안내
# - 원인 표현은 단정 대신 “가능성이 높음” 형태 사용

# TODO: Retrieval 고도화
# - BM25 키워드 검색 추가
# - Vector Search + Keyword Search 결과를 RRF 기반 Hybrid Search로 병합
# - min_score / confidence threshold 튜닝

# TODO: Agent Layer 고도화
# - Query Intent Analyzer 노드 추가
# - Confidence Judge 노드 분리
# - Answer Generator 노드 개선

# TODO: Evaluation 추가
# - 테스트 질문 세트 작성
# - 기대 incident / 실제 Top1 / score / confidence 기록
# - Retrieval 품질 개선 전후 비교

# TODO: Retrieval Evaluation 저장
# - query
# - retrieved incident
# - vector score
# - confidence score
# - 최종 answer
# - 추후 검색 품질 분석 및 threshold 튜닝에 활용


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("app").setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    init_db()
    yield


app = FastAPI(title="IncidentLens Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
