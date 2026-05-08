# Incident Lens

과거 장애 사례를 검색해 현재 문제 해결에 활용하는 사내 장애 사례 검색 에이전트입니다.<br/>
LLM이 답을 생성하는 구조가 아닌, 과거 사례를 검색하고 그 맥락을 정리하는 구조로 설계했습니다.

---

## 데이터 구조

### 활용 데이터

LLM은 보조 역할이며, 핵심은 검색과 데이터 구조에 있습니다.<br/>
세 가지 데이터를 핵심으로 합니다.

- **로그(Log)**: 문제의 증상
- **장애 티켓(Ticket)**: 원인과 대응 과정
- **PR/커밋(Commit)**: 실제 해결 방법

위의 세 가지 데이터를 핵심으로 한 이유는 장애의 발생부터 해결까지의 흐름을 구성하기 때문입니다.

---

## 데이터 수집 파이프라인

원본 이벤트(`error_log_events`, `ticket_events`, `pr_events`)는 별도로 저장하고<br/>
incident 레코드는 하나를 생성한 뒤 단계적으로 업데이트하는 방식으로 운영합니다.

**1단계 — 에러 로그 발생**
- Raw log event 저장 및 incident 후보 생성 (status: `open`)
- incident에는 프로젝트명, 발생 시각, 주요 에러 메시지, 서비스/모듈 정보가 기록됩니다.

**2단계 — 티켓 생성**
- Raw ticket event 저장
- 미해결 incident 후보들과 연관성 점수를 계산해 가장 적절한 incident에 연결 (status: `investigating`)

**3단계 — PR/MR 생성**
- Raw PR event 저장
- 관련 티켓 또는 incident 기준으로 연결 추론 후 해결 요약 보강
- 머지 완료 시 status: `resolved`

### 에러 로그와 티켓/PR 매핑

초기 장애 로그와 후속 티켓은 동일한 식별자로 직접 연결되지 않으므로,<br/>
아래 규칙을 우선순위대로 스코어링해 연결 후보를 생성합니다.

1. 같은 프로젝트 여부
2. 같은 서비스 또는 모듈 여부
3. 장애 발생 후 N시간 이내 생성된 티켓 여부
4. 에러 요약과 티켓 요약의 의미 유사도

PR/MR의 경우, 프로젝트/시간/모듈 정보로 후보를 좁힌 뒤 변경 코드(diff)를 LLM이 분석해<br/>
장애 해결과의 관련성을 보조적으로 판단하도록 설계했습니다.

---

## 데이터 전처리

**1차 — 규칙 기반 파싱**
패턴 매칭으로 확정적으로 추출 가능한 사실 데이터를 뽑습니다. (`log_level`, `error_type`, `class_name`, `method_name`, `stack_trace` 일부, 에러 메시지 본문 등)

**2차 — LLM 보정/정리**
1차 파싱 결과를 검증·보정하고, `normalized_summary`, `suspected_cause` 등 LLM 추론이 필요한 필드를 생성합니다.

예시:
- `ClassNotFoundException` → 클래스 로딩 실패
- `NullPointerException` → 널 참조 오류
- `ConnectionTimeout` → 외부 연결 시간 초과

---

## 운영 파이프라인

```
1. Raw 데이터 수집 (logs / tickets / PRs)
2. Incident 생성 및 업데이트
3. Incident 기반 임베딩 생성 (검색용 embedding text → 벡터 저장)
4. Retrieval (키워드 검색 + 벡터 검색, RRF로 결합)
5. 가설 생성 (검색된 incident 기반 원인 후보 생성)
6. 가설 검증 (근거 incident / ticket / PR / log 확인, 근거 약한 가설 순위 하향)
7. Confidence 산출 (검색 점수, 근거 수, 동일 프로젝트 여부, 해결 PR 연결 여부)
8. 최종 응답 생성 (가설, 근거 incident, 체크포인트, confidence 포함)
9. Trace 저장 (쿼리, 후보 incident, 생성된 가설, confidence 산출 근거 등 중간 과정 기록)
```
