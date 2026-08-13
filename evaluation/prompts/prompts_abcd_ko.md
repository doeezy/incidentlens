# Prompt A/B/C/D 한국어 번역 모음

> 실제 Prompt A/B/C/D Evaluation에는 영어 원문 txt 파일이 사용되었습니다. 이 문서는 리뷰와 설명을 위한 한국어 번역본입니다.

## Prompt A - Minimal Prompt

원문: [prompt_a.txt](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_a.txt)  
번역: [prompt_a_ko.md](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_a_ko.md)

가장 단순한 baseline prompt입니다. 사용자 query와 검색된 Incident 후보를 제공하고, 가장 관련 있는 Incident를 선택해 JSON 형태로 반환하도록 요청합니다.

## Prompt B - Structured Prompt

원문: [prompt_b.txt](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_b.txt)  
번역: [prompt_b_ko.md](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_b_ko.md)

Role, Task, Rules, Evidence, Output Schema를 명확히 분리한 prompt입니다. 제공된 Incident 후보 정보만 evidence로 사용하고, root cause evidence가 없으면 Root Cause를 만들거나 확정하지 않도록 지시합니다.

## Prompt C - Evidence First

원문: [prompt_c.txt](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_c.txt)  
번역: [prompt_c_ko.md](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_c_ko.md)

결론을 먼저 내지 않고, query에서 관찰 가능한 사실과 후보별 supporting/contradictory evidence를 먼저 검토한 뒤 Incident를 선택하도록 설계한 prompt입니다. 내부 chain-of-thought는 노출하지 않고, 평가 가능한 구조화 결과만 반환하도록 지시합니다.

## Prompt D - Compressed Context

원문: [prompt_d.txt](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_d.txt)  
번역: [prompt_d_ko.md](/Users/doeezy/Documents/toy-project/incidentlens/evaluation/prompts/prompt_d_ko.md)

Structured prompt 형태를 유지하되, 판단에 필요한 compact field만 전달하는 prompt입니다. context 압축으로 생략된 정보를 추론하지 않고, compact evidence로 충분하지 않은 필드는 답변 불가능으로 표시하도록 지시합니다.
