# 09 – Service Execution: ProcessGPT/deepagent 실행 모드 출력 계약

**목적**: 이 skill 은 두 가지 환경에서 실행될 수 있다.

1. **대화형(Claude Code) 모드** — 사용자와 직접 대화하며 `.bpmn/` 폴더에 산출물(`process-definition.json`, `forms/*.html`)을 저장한다. (기본 동작, 0~8단계 그대로)
2. **서비스(ProcessGPT deepagent) 모드** — `process-gpt-deepagents` 서버가 이 skill 을 스킬 볼륨(`/app/skills/<tenant_id>/bpmn-process-generation-skill/`)에서 로드해 실행한다. 이 경우 **로컬 파일 시스템에 `.bpmn/` 를 쓰지 않고**, 최종 결과를 **하나의 JSON 산출물**로 반환해야 프론트엔드(process-gpt-vue3)가 받아 DB에 저장(persist)할 수 있다.

> 이 문서는 서비스 모드에서의 **출력 계약(output contract)** 만 정의한다. 컨설팅·생성 규칙(0~8단계)은 그대로 따른다. 단, 서비스 모드에서는 파일 저장 대신 아래 JSON 을 최종 응답으로 emit 한다.

---

## 모드 판별

- 실행 컨텍스트에 사용자 작업 디렉토리(`.bpmn/` 를 만들 수 있는 로컬 FS)가 없고, ProcessGPT 테넌트/프로세스 컨텍스트(tenant_id, proc_def_id 등)가 주어지면 **서비스 모드**다.
- deepagent 가 이 skill 을 호출할 때는 보통 시스템 프롬프트/요청에 "프로세스 정의를 생성해 반환하라" 는 취지가 들어온다. 이 경우 서비스 모드로 동작한다.
- 애매하면 **서비스 모드**를 기본으로 한다(파일 쓰기 부작용이 없으므로 안전).

---

## 출력 계약 (서비스 모드 최종 응답)

서비스 모드의 **최종 응답은 아래 형태의 valid JSON 객체 하나**여야 한다. 설명 텍스트로 감싸지 말고(또는 감싸더라도 JSON 블록이 명확히 파싱되게), 마지막에 이 JSON 을 단독으로 emit 한다. deepagent 의 `done` 이벤트 `content` 로 그대로 전달된다.

```json
{
  "type": "process-definition-result",
  "processDefinition": {
    "processDefinitionName": "휴가신청 프로세스",
    "processDefinitionId": "leave_request_process",
    "description": "...",
    "isHorizontal": true,
    "data": [ ... ],
    "roles": [ ... ],
    "elements": [ ... ],
    "subProcesses": [],
    "dmn_decisions": [ ... ],
    "dmn_rules": [ ... ]
  },
  "forms": [
    { "activity_id": "leave_request", "form_id": "leave_request_leave_request_form", "html": "<section>...</section>" }
  ],
  "agents": [
    {
      "id": "hr_leave_review_agent",
      "name": "인사 휴가검토 에이전트",
      "role": "휴가 신청을 검토·승인하는 인사 담당",
      "goal": "잔여 연차일수와 신청 휴가일수를 비교해 승인/반려를 일관되게 판단",
      "persona": "꼼꼼하고 규정을 준수하는 인사 담당자 말투",
      "tools": "",
      "skills": ["휴가 잔여일수 검증"],
      "activity_ids": ["review_approval"]
    }
  ],
  "skills": ["휴가 잔여일수 검증"],
  "bpmn": null
}
```

### 필드 규칙

- **`processDefinition`**: [02-generate-definition.md](02-generate-definition.md) 의 최상위 구조를 **그대로** 사용한다. 이 객체가 곧 프론트의 `proc_def.definition` 으로 저장된다.
  - 스킬/에이전트(4·5단계) 반영분(`activity.skills`, `activity.agent`, `activity.tool`, `agentMode`, `orchestration`)을 포함한다.
  - DMN(6단계)은 `dmn_decisions` / `dmn_rules` 로 `processDefinition` **안에** 넣는다(별도 최상위 아님).
  - 참조정보(8단계) `activity.inputData`, gateway `conditionData` 도 `processDefinition` 안에 포함.
- **`forms`**: 각 UserActivity 폼. `activity_id`(필수), `form_id`(권장: `<procId>_<activityId>_form`), `html`(7단계 컴포넌트 규격 HTML). 프론트가 `form_def` 에 저장한다.
- **`agents`**: 5단계에서 만든 에이전트 프로필 목록(없으면 생략/`[]`). 각 항목은 pdf2bpmn `_insert_agent_user` 의 필드와 동일:
  - `id`(필수): 에이전트 식별자. **`processDefinition` 의 `activity.agent` 및 `roles[].endpoint` 와 동일한 값**이어야 참조가 연결된다.
  - `name`, `role`, `goal`, `persona`, `tools`(문자열, 없으면 `""`), `skills`(이 에이전트에 매핑할 스킬명 배열), `activity_ids`(담당 활동).
  - 프론트가 `users`(is_agent=true) 에 생성하고, `skills` 를 `agent_skills` + `users.skills` 로 매핑한다(중복은 username/role 기준 재사용).
- **`skills`**: 3·4단계에서 사용자가 선택해 만든 재사용 스킬명 목록(없으면 `[]`). 프론트가 `tenants.skills` 에 등록한다.
- **`bpmn`**: 기본 `null`. (pdf2bpmn 과 동일하게 XML 은 비워두고 `definition` 만 저장한다. 프론트가 필요 시 모델러로 렌더한다.)

> 한 번의 응답에 위 전체를 담는다. 사용자 개입(HITL)이 필요한 단계(3단계 후보 선택)는 deepagent 의 HITL(`request_human_input`) 로 질문하고, 답을 받은 뒤 최종 JSON 을 emit 한다.

---

## 서비스 모드에서 단계 진행

- 0~8단계의 **규칙·품질 기준은 동일**하다. 다만 산출물 저장 위치만 다르다:
  - 파일(`.bpmn/process-definition.json`, `forms/*.html`)을 쓰는 대신 **메모리에 누적**했다가 최종 JSON 으로 emit.
  - 단계별 "다음 단계로 넘어갈까요?" 식의 확인은 서비스 모드에서도 3단계(스킬/에이전트/DMN 선택) 한 번만 HITL 로 받고, 폼·참조정보는 자동 진행(SKILL.md 의 자동 진행 원칙 그대로).
- 컨설팅(1단계) 흐름 합의도 deepagent 채팅으로 진행 가능하다. 다만 최종 산출물은 반드시 위 출력 계약 JSON 이어야 한다.

---

## 프론트엔드 연동 (참고)

- deepagent 호출: `process-gpt-vue3` 의 `DeepAgentRouterService.sendMessageStream()` → `POST /process-gpt-deepagents/chat/stream` (SSE). 최종 결과는 `done` 이벤트의 `content`.
- 저장: 프론트 `ProcessGPTBackend.saveGeneratedProcessArtifacts(result)` 가 위 JSON 을 받아 `putRawDefinition`(proc_def + form_def + proc_def_version) · `saveSkills`(tenants.skills) 로 persist 한다. (pdf2bpmn 의 `_save_proc_def`/`_save_form_def`/스킬 동기화와 동일 결과)
- 스킬 등록(이 skill 자체를 deepagent 가 쓰게 하려면): `ProcessGPTBackend.uploadSkills({type:'url', url})` → `/claude-skills/skills/upload-from-github` 로 이 skill 저장소를 테넌트 스킬 볼륨에 업로드한다(또는 `{type:'file'}` ZIP 업로드).
