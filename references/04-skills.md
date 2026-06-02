# 04 – Skills: 재사용 스킬 카드 생성 + JSON 반영

**목적**: 3단계에서 사용자가 고른 스킬 후보를, 한 명의 운영자가 그대로 따라할 수 있는 **SOP(표준 작업 절차) 스킬 카드** 한 장으로 정제해 `.bpmn/skills/<safe-name>.md` 로 저장하고, 프로세스 정의 JSON 의 해당 Activity 와 `skills` 목록에 연결한다.

> 이 규칙은 pdf2bpmn 의 `skill_enricher.py`(EnrichedSkill 스키마 + render_skill_markdown) 을 옮긴 것입니다. 카드 구조를 그대로 따르세요.

산출물:
- `.bpmn/skills/<safe-name>.md` (스킬 카드, 선택된 스킬마다 1개)
- `process-definition.json` 업데이트 (`skills[]` 추가 + 관련 `activity.skills` 채움)

템플릿: [assets/templates/skill-card.md](../assets/templates/skill-card.md)

---

## 스킬 카드 만들기

선택된 각 스킬에 대해, 근거가 된 Activity 들(`source_activity_ids`)의 `name`/`description`/`instruction` 을 종합해 아래 필드를 채운다:

| 필드 | 규칙 |
|------|------|
| `safe_name` | 영문 소문자 + 하이픈(kebab-case), 3~6 단어. 한글/공백/특수문자 금지. 예: `leave-balance-check` |
| `name` | 도메인 의미가 분명한 **한국어 명사구**. "공통지침", "기타", "스킬", "절차" 같은 일반·형식적 단어 금지. 예: "휴가 잔여일수 검증" |
| `description` | frontmatter 용 1~2 문장 (무엇을·언제). |
| `summary` | 3~5 문장 개요. 무엇을, 왜, 어떤 산출물로 만드는지. |
| `when_to_use` | 사용 시점/트리거를 질문·조건 형태로 4~6개. |
| `inputs` | 필요한 입력/사전 조건(서류·레코드·결과코드 등 명사구) 3~5개. |
| `outputs` | 결과물/산출물 2~4개. |
| `procedure` | 단계별 절차 4~7단계. 각 단계 `{ title(한국어 짧은 제목), detail(2~4문장 구체 설명) }`. |
| `examples` | 구체 시나리오 1~2개. 각 `{ scenario, input, output }` 모두 한국어. |
| `notes` | 운영 시 주의/제약/정책 3~5개. |

safe_name 이 겹치면 `-2`, `-3` 접미사를 붙여 유일하게 만든다.

---

## 스킬 카드 파일 형식 (`.bpmn/skills/<safe-name>.md`)

`render_skill_markdown` 과 동일한 섹션 구조로 저장한다:

```markdown
---
name: "휴가 잔여일수 검증"
description: "신청 전 신청자의 잔여 연차를 확인해 신청 가능 여부를 판단한다."
---

# 휴가 잔여일수 검증

## 개요
(summary 3~5문장)

## 사용 시점
- (when_to_use 항목들)

## 입력 / 사전 조건
- (inputs 항목들)

## 산출물
- (outputs 항목들)

## 절차
### 1. (title)
(detail)
### 2. (title)
(detail)
...

## 실전 예시
### 예시 1: (scenario)
- 입력: (input)
- 산출: (output)

## 주의사항
- (notes 항목들)

## 출처 (Source Activities)
- coverage: (근거 활동 수)
- activities: (activity id 목록)
- canonical: (대표 원문 문장)
```

---

## 프로세스 정의 JSON 반영

`.bpmn/process-definition.json` 을 직접 Edit 한다 ([02-generate-definition.md](02-generate-definition.md) 의 "프로세스 변경(수정) 형식" 규칙 준수):

1. **최상위 `skills` 배열에 추가** (없으면 만든다). 각 항목:
   ```json
   { "id": "<safe_name>", "name": "<한국어 스킬명>", "description": "<요약>" }
   ```
2. **근거 Activity 의 `skills` 에 그 스킬 id 추가**:
   ```json
   "skills": ["leave-balance-check"]
   ```
   - `source_activity_ids` 에 든 모든 Activity 에 해당 스킬 id 를 넣는다.
3. 스킬이 배정된 Activity 는 자동화 정책상 다음을 함께 설정한다(있으면 유지, 없으면 추가):
   ```json
   "agentMode": "complete",
   "orchestration": "deepagents"
   ```

> 메인 `elements` 의 Activity 와, (서브프로세스가 있다면) 서브프로세스 `children.activities` 양쪽 모두에서 id 가 일치하는 항목에 반영한다.

---

## 사용자에게 보여주기

- 만든 스킬마다 한 줄 요약: "**휴가 잔여일수 검증** — 신청 전 잔여 연차 확인 (활동 2개에 연결). `.bpmn/skills/leave-balance-check.md`"
- raw JSON 을 들이밀지 말고 자연어로.

## 다음 단계 연결

3단계에서 에이전트/DMN 도 골랐으면 그 단계로, 아니면:

> "스킬을 붙였어요. 다음은 [에이전트 연결 / DMN 규칙 / 폼 생성] 입니다."

처리 순서대로 [05-agents.md](05-agents.md) → [06-dmn.md](06-dmn.md) → [07-forms.md](07-forms.md) 로 이어집니다.
