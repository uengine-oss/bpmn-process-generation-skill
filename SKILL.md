---
name: bpmn-process-generation
description: 사용자가 만들고 싶은 업무 프로세스를 컨설팅한 뒤 ProcessGPT 서비스용 BPMN 프로세스 정의(JSON)를 단계별로 생성하는 가이드. 사용자가 "프로세스 만들고 싶어", "업무 흐름 자동화", "휴가 신청 프로세스 만들어줘", "결재 프로세스 설계", "BPMN 만들어줘", "워크플로우 만들어줘", "/bpmn", "/bpmn:consult", "/bpmn:generate", "프로세스 정의 생성", "이 업무를 프로세스로 만들고 싶다" 같은 표현을 쓰거나, 어떤 반복 업무·승인 흐름·자동화하고 싶은 절차를 설명하면서 그것을 실행 가능한 프로세스로 만들고 싶어할 때 반드시 트리거하세요. BPMN에 익숙하지 않은 사용자도 컨설팅(초안 제안·질문)을 통해 흐름을 함께 다듬고, 스킬·에이전트·DMN 규칙·폼·참조정보까지 단계별로 붙여 완성된 프로세스 정의 JSON을 만들 수 있도록 안내합니다.
---

# BPMN Process Generation

사용자가 만들고 싶은 업무 프로세스를 **컨설팅 → 프로세스 정의(JSON) 생성 → 스킬/에이전트/DMN 선택 생성 → 폼 생성 → 참조정보 연결**의 순서로 함께 만들어가는 skill입니다. speckit 의 `/speckit.specify → /speckit.plan → /speckit.tasks` 처럼 **각 단계가 산출물을 만들고, 그 산출물이 다음 단계의 입력이 됩니다**. 이 skill의 핵심 책임:

1. 사용자가 BPMN을 몰라도 **말로 설명한 업무를 흐름(초안)으로 바꿔** 제안하고, 질문으로 함께 다듬는다 (컨설팅).
2. 사용자가 초안에 동의하면 **우리 서비스 규격의 프로세스 정의 JSON** 을 [생성 규칙](references/02-generate-definition.md) **그대로** 생성한다.
3. 생성된 프로세스에서 **스킬·에이전트·DMN 규칙 후보**를 뽑아 사용자에게 *무엇을 생성할지* 묻고(HITL), 선택한 것만 만들어 JSON에 반영한다.
4. 각 액티비티의 **폼(입력 양식)** 을 만들고, **참조정보(inputData/conditionData)** 를 연결해 JSON을 최종 업데이트한다.

> 검증(validation) 단계는 이 skill 범위에서 **제외**합니다. (pdf2bpmn 에는 실행 검증 단계가 있지만 여기서는 다루지 않습니다.)

> **실행 모드**: 이 skill 은 (1) **대화형(Claude Code)** — `.bpmn/` 폴더에 산출물 저장, 또는 (2) **서비스(ProcessGPT deepagent)** — 파일 대신 단일 JSON 산출물을 만들고, 스킬에 포함된 후처리 스크립트([scripts/](scripts/))로 **pdf2bpmn 와 동일하게 Supabase 저장(proc_def/form_def/users/agent_skills/tenants.skills) + 실행 검증(process-gpt-completion)** 까지 직접 수행, 두 모드로 동작합니다. 서비스 모드 규격·후처리 실행 절차는 [references/09-service-execution.md](references/09-service-execution.md) 를 따릅니다.

---

## 전체 흐름 (overview)

| # | 단계 | 무엇을 하나 | 산출물 | 사용자 개입 |
|---|------|------------|--------|------------|
| 0 | **Orientation** | 진입 패턴 판별, 초심자/숙련자 모드 결정 | (없음) | — |
| 1 | **Consulting** | 업무 설명을 듣고 **흐름 초안 제안** + 핵심 질문으로 다듬기 | `.bpmn/01-consulting.md` | 질문/답변, 초안 승인 |
| 2 | **Generate Definition** | 승인된 초안을 **프로세스 정의 JSON** 으로 생성 | `.bpmn/process-definition.json` | (자동, 승인 후) |
| 3 | **Elicit Artifacts** | 스킬/에이전트/DMN **후보를 종류별 3개 내외 자동 추천** → 클릭 선택(+기타 자유 입력) | (사용자 선택) | **핵심 HITL — 마지막 질문** |
| 4 | **Build Artifacts** | 선택된 스킬/에이전트/DMN 생성 + JSON 반영 | `.bpmn/skills/*.md` + JSON 업데이트 | — (자동) |
| 5 | **Forms** | 각 액티비티 **입력 폼** 생성 + JSON 반영 | `.bpmn/forms/*.html` + JSON 업데이트 | — (자동) |
| 6 | **Reference Info** | **inputData/conditionData** 참조 연결 + JSON 반영 | JSON 최종 업데이트 | — (자동) |

> **자동 진행 원칙 (중요)**: 사용자 개입은 **3단계의 후보 선택 한 번**으로 끝납니다. 그 답변 직후 **4·5·6단계(아티팩트 생성 → 폼 생성 → 참조정보 연결)는 추가 질문 없이 연속 자동 실행**되고, **마지막에 한 번** 무엇이 생성되었는지 요약 + "수정이 필요하면 말씀해 주세요" 안내를 합니다. 폼·참조정보는 어떤 프로세스든 항상 만들어야 하므로 "만들까요?" 를 묻지 않습니다.

> **핵심 원칙**: 컨설팅(1단계)에서는 *BPMN 규칙에 맞는 흐름*을 초안으로 제시하되 사용자가 이해하기 쉽게 설명합니다. 반면 프로세스 정의 JSON(2단계)과 그 이후의 스킬/폼/참조정보 구조는 **우리 서비스에 맞춰 정의된 규격이므로 reference 에 적힌 규칙 그대로** 생성해야 합니다. 흐름은 유연하게, 출력 구조는 엄격하게.

---

## 사용자 진입 패턴

사용자가 이 skill을 호출하는 방식은 크게 3가지입니다. 어떤 경우든 **첫 응답에서는 [references/00-orientation.md](references/00-orientation.md) 의 판별**부터 합니다 (이미 진행 중인 세션 제외).

### A. 처음 시작 ("프로세스 만들고 싶어", "/bpmn", "휴가 신청 프로세스 만들어줘")

→ **컨설팅 단계(1)** 로 진입. 사용자가 만들고 싶은 게 무엇인지 한두 마디라도 있으면 바로 [references/01-consulting.md](references/01-consulting.md) 규칙대로 **흐름 초안을 먼저 제안**합니다. 정보가 거의 없으면(예: "영업이익 10% 올리고 싶어") 흐름을 추측해 만들지 말고 먼저 현황을 묻습니다.

### B. 특정 단계 직접 호출 (`/bpmn:generate`, "이제 폼 만들어줘", "DMN 규칙 붙여줘")

→ 해당 단계의 reference 만 로드해 진행. 단, 이전 단계 산출물(`.bpmn/` 내 파일)이 없으면 *"아직 프로세스 정의가 없는데, 컨설팅부터 짧게 하고 올까요?"* 라고 한 번 묻습니다.

### C. 진행 중 세션 재개 ("어디까지 했지?", "이어서 하자")

→ `.bpmn/` 디렉토리에서 `process-definition.json` 과 마지막 산출물을 확인해 현재 위치를 요약하고, 다음 단계를 제안합니다.

---

## 단계 진행 루프 (모든 단계 공통)

각 단계는 아래 루프로 수행하고, 마지막에 다음 단계로 자연스럽게 연결합니다.

### Step 1: 단계 reference 읽기
`references/<NN>-<step>.md` 를 Read 로 로드합니다. 거기엔 그 단계의 **목적, 규칙, 사용자에게 던질 질문, 산출물 구조, 다음 단계 연결 멘트**가 있습니다.

### Step 2: 사용자에게 단계 소개 (초심자 배려)
- 이전 단계 산출물(`.bpmn/`)을 훑어 컨텍스트를 잡는다.
- "이번 단계는 X 입니다. 여기서 Y 를 만듭니다." 라고 짧게 알린다.
- 사용자가 BPMN 초심자면 용어(액티비티/게이트웨이/시퀀스 등)를 30자 이내로 풀어 설명한다.

### Step 3: 인터랙티브하게 산출물 만들기
- reference 의 규칙대로 진행한다. **질문은 한 번에 하나씩** (컨설팅 단계), 또는 선택형 질문(HITL 단계)으로.
- 산출물을 `.bpmn/` 의 해당 파일에 저장/업데이트한다.

### Step 4: 산출물 리뷰 + 다음 단계 제안
- 무엇이 만들어졌는지 한 줄 요약 + 파일 경로를 보여준다.
- **0~3단계**(컨설팅·JSON 생성·후보 선택)는 사용자 확인을 받아 다음으로 넘어간다. 단, 3단계 선택 답변을 받은 **이후 4·5·6단계는 추가 질문 없이 자동으로 이어서** 수행하고 **마지막에 한 번만** 통합 요약·수정 안내를 한다(중간에 "다음으로 넘어갈까요?" 금지).
- 다음 reference 를 로드해 Step 1 로 돌아간다.

---

## 산출물 보관 규칙

사용자의 현재 작업 디렉토리에 `.bpmn/` 폴더를 만들고 그 안에 모든 산출물을 저장합니다 (speckit의 `.specify/`, DDD의 `.ddd/` 와 동일한 패턴).

```
.bpmn/
├── 01-consulting.md            # 컨설팅 대화 요약 + 합의된 흐름 초안
├── process-definition.json     # 메인 산출물. 2단계에서 생성, 4~6단계에서 계속 업데이트
├── skills/                     # 4단계에서 생성된 스킬 카드
│   ├── <safe-name>.md
│   └── ...
└── forms/                      # 5단계에서 생성된 폼 HTML
    ├── <activity_id>.html
    └── ...
```

**규칙:**
- 사용자의 현재 작업 디렉토리에 만든다 — skill 디렉토리에 만들지 않는다.
- `.bpmn/` 가 없으면 첫 단계 시작 시 자동으로 만든다.
- `process-definition.json` 은 **하나의 파일을 계속 업데이트**한다. 2단계에서 만든 뒤 4·5·6단계가 같은 파일에 필드를 추가/수정한다.
- 사용자가 만든 산출물을 임의로 덮어쓰지 않는다. 이미 있으면 "덮어쓸까요, 이어서 수정할까요?" 묻는다.

---

## BPMN 초심자 vs 숙련자 분기

[references/00-orientation.md](references/00-orientation.md) 에서 사용자를 두 부류로 나눕니다. 기본은 **초심자 모드** 입니다.

**초심자 모드** (BPMN 용어 잘 모름):
- 단계 시작 시 평범한 말로 한 문장 설명 추가
- 용어(액티비티=사람이 하는 일 한 단계, 게이트웨이=갈림길, 시퀀스=화살표 등) 처음 등장 시 짧은 정의 병기
- 컨설팅 초안은 항상 "1. ~ 단계 / 2. ~ 단계" 형태로 말로 풀어 보여줌
- 출력 JSON 의 세부 구조는 사용자에게 강요하지 않고, 결과만 자연어로 요약

**숙련자 모드** ("BPMN 익숙해", "용어 설명 빼"):
- 용어 설명 생략, 빠르게 진행
- 필요하면 JSON 구조를 직접 보여주며 진행

---

## 절대 하지 말 것

- **컨설팅 없이 바로 JSON 부터 만들지 않는다.** 사용자가 명시적으로 "그냥 바로 생성해" 라고 하거나, 이미 충분히 흐름을 설명한 경우가 아니면 1단계 컨설팅으로 흐름 초안을 먼저 합의한다.
- 컨설팅에서 **시스템/도구/프로그램을 무엇을 쓰는지 묻지 않는다.** (우리가 그 도구를 만들어주기 때문 — 사용자에게 혼란만 준다.) 소요 시간 등 프로세스 정의에 불필요한 질문도 하지 않는다. 자세한 금지 질문은 [references/01-consulting.md](references/01-consulting.md) 참조.
- 2단계 JSON 은 **reference 의 생성 규칙을 그대로** 따른다. ID는 영문 소문자+언더스코어, 이름/설명은 한글, StartEvent·EndEvent·Sequence 필수 등 — 임의로 구조를 바꾸지 않는다.
- 3단계에서 **사용자에게 묻지 않고** 스킬/에이전트/DMN 을 임의로 다 생성하지 않는다. 반드시 후보를 보여주고 선택을 받는다 (HITL). 후보는 종류별로 **3개 내외 자동 추천**하고, 커스텀은 `AskUserQuestion` 의 자동 "기타" 입력으로 받는다(옵션에 "기타"를 직접 만들지 않는다).
- **폼·참조정보(5·6단계)는 "만들까요?" 묻지 않는다.** 항상 생성·연결해야 하는 필수 산출물이므로, 3단계 답변 직후 4·5·6단계를 **자동 연속 실행**하고 마지막에 한 번만 결과를 요약·수정 안내한다.
- 단, **1·2·3단계 사이**에서는 사용자 확인 없이 단계를 몰아서 진행하지 않는다(컨설팅 합의 → JSON 생성 → 후보 선택은 각각 사용자 개입 지점).
- 산출물에 placeholder만 남기지 않는다. 사용자와 대화해 **실제 내용으로** 채운다.

---

## 참조 문서

이 skill 본문은 흐름만 담고, 각 단계의 디테일·규칙은 reference 에 분리되어 있습니다. 단계 진입 시 해당 파일만 읽으면 됩니다.

| 파일 | 무엇이 들어있나 |
|------|----------------|
| [references/00-orientation.md](references/00-orientation.md) | 진입 패턴 판별, 초심자/숙련자 모드, 정보 부족 시 대응 |
| [references/01-consulting.md](references/01-consulting.md) | **컨설팅 규칙** — 흐름 초안 제안법, 금지 질문, 질문 방식, 생성 제안 타이밍 |
| [references/02-generate-definition.md](references/02-generate-definition.md) | **프로세스 정의 JSON 생성 규칙(엄격)** — 전체 스키마, 요소 타입, 역할/서브프로세스 규칙 |
| [references/03-elicit-artifacts.md](references/03-elicit-artifacts.md) | **HITL** — 스킬/에이전트/DMN 후보 도출 + 선택 질문 방식 |
| [references/04-skills.md](references/04-skills.md) | 스킬 카드 생성 규칙 + JSON 반영(`activity.skills`, `roles`/`skills`) |
| [references/05-agents.md](references/05-agents.md) | 에이전트(역할) 생성 규칙 + JSON 반영(`activity.agent`, `roles`) |
| [references/06-dmn.md](references/06-dmn.md) | DMN 의사결정/규칙 생성 + JSON 반영(`dmn_decisions`, `dmn_rules`) |
| [references/07-forms.md](references/07-forms.md) | 폼 HTML 생성 규칙(컴포넌트 규격) + JSON 반영(`activity.tool`) |
| [references/08-reference-info.md](references/08-reference-info.md) | 참조정보 — `activity.inputData`, gateway `conditionData` 연결 |
| [references/09-service-execution.md](references/09-service-execution.md) | **서비스(ProcessGPT deepagent) 실행 모드** — `.bpmn/` 파일 대신 단일 JSON 산출물로 반환하는 출력 계약. 프론트가 받아 DB 저장 |

템플릿은 [assets/templates/](assets/templates/) 에 있습니다. 각 단계 reference 에서 어떤 템플릿을 쓸지 명시합니다.

---

## 출처

이 skill 의 컨설팅·프로세스 정의·스킬/DMN/폼/참조정보 생성 규칙은 사내 **ProcessGPT / pdf2bpmn** 프로젝트의 정의를 기반으로 합니다. 흐름·진행 방식은 [ddd-starter-modelling-process](https://github.com/ddd-crew/ddd-starter-modelling-process) 스타일과 GitHub Spec Kit 의 단계형 사용 방식을 참고했습니다.
