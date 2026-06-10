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

## 표시 모드: 기존 프론트 UI 에 프로세스 프리뷰 렌더

프론트(`process-gpt-vue3`)의 `Chat.vue` 는 **에이전트 메시지 content 에 `processDefinitionId` + `elements` 가 든 JSON 이 있으면 자동으로 인라인 BPMN 프리뷰를 렌더**한다 (`isProcessJsonMessage` → `getDisplayMessageContent` → `openInlineProcessPreview` → `emitPreviewBpmn` → `preview-bpmn` 이벤트). **프론트 코드 수정 불필요.**

따라서 서비스 모드에서 **화면 표시가 필요하면**, 최종 응답 메시지에 **elements 형식(02-generate-definition 규격, `processDefinitionId` + `elements[]`)의 processDefinition JSON 을 포함**한다. 권장 형식:

````
프로세스를 생성했어요. (요약: 단계 N개, 분기 …)

```json
{ "processDefinitionId": "leave_request_process", "processDefinitionName": "...", "elements": [ ... ], "roles": [ ... ], ... }
```
````

- Chat.vue 가 raw JSON 블록을 **숨기고** "프로세스가 생성되었습니다." 로 치환한 뒤 프리뷰를 띄운다.
- 반드시 **flattened 가 아니라 `elements[]` 형식**이어야 한다(프론트 프리뷰가 기대하는 형식). 저장용 flattened 변환은 `scripts/` 가 내부에서 처리한다.

### 표시 vs 저장 (충돌 정리)
- **표시(Chat.vue 프리뷰)는 저장이 아니다** — 렌더만 한다.
- 저장 경로는 **하나만** 쓴다:
  - (A) 스킬 후처리 `scripts/run_postprocess.py` 로 저장(아래) — 이 경우에도 표시용 JSON 은 메시지에 넣어도 무방하다(프리뷰는 중복 저장 아님). 단, 프론트 `ChatRoomPage.onDone` 의 자동저장 훅을 **켜두지 않는다**(스크립트가 이미 저장하므로 이중 저장 방지).
  - (B) 프론트 저장(`saveGeneratedProcessArtifacts`/onDone) — 이 경우 스킬은 표시용 JSON 만 emit 하고 `scripts/` 후처리는 실행하지 않는다.
- 요약: **표시용 JSON emit 은 항상 가능**, **저장은 A 또는 B 중 하나만**.

---

## 후처리: 저장 + 검증을 스킬이 직접 수행 (권장)

서비스 모드에서는 출력 계약 JSON 을 만든 뒤, **스킬에 포함된 후처리 스크립트(`scripts/`)** 를 deepagent 샌드박스에서 실행해 pdf2bpmn 와 **동일하게 저장·검증까지** 끝낸다. (프론트 저장 로직에 의존하지 않는다.)

deepagent 샌드박스 도구(`sandbox_write_files_and_run` / `sandbox_run_shell`)는 `subprocess.run(shell=True, env=merged_env)` 로 임의 코드 실행·아웃바운드 네트워크가 가능하고, **deepagent 런타임의 환경변수(`SUPABASE_URL`/`SERVICE_ROLE_KEY`/`COMPLETION_ENGINE_URL` 등)를 그대로 상속**한다. 따라서 스킬 스크립트가 그 키로 Supabase 에 직접 write 하고 실행 엔진을 호출할 수 있다.

### 실행 절차 (에이전트가 따라야 할 것)
1. 위 출력 계약 JSON 을 샌드박스 파일로 쓴다. 예: `result.json`.
2. 후처리 스크립트를 실행한다:
   ```bash
   pip install -r <skill_dir>/scripts/requirements.txt
   python <skill_dir>/scripts/run_postprocess.py --input result.json --tenant <tenant_id>
   ```
   - `<skill_dir>` 는 마운트된 스킬 경로(`/app/skills/<tenant_id>/bpmn-process-generation-skill`).
   - `tenant_id` 는 요청 컨텍스트에서 받는다.
   - 검증을 끄려면 `--no-validate`.
3. 스크립트가 출력하는 요약 JSON(`{"saved": {...}, "validation": {...}}`)을 사용자에게 보고한다.

> ⚠️ **이중 저장 방지**: 스킬 후처리(저장)를 수행했다면, 최종 `done` 응답은 **사람이 읽는 요약**(저장된 proc_def/폼/에이전트/검증 결과)으로 emit 하고 **출력 계약 JSON(`processDefinition` 통째)을 최종 텍스트로 내보내지 않는다.** (프론트 `ChatRoomPage.onDone` 의 자동 저장 훅은 `processDefinition` 포함 JSON 을 감지해 다시 저장하므로, 스킬이 이미 저장한 경우 contract JSON 을 최종 메시지로 내보내면 중복 저장된다.) contract JSON 은 샌드박스 `result.json` 파일로만 쓰고 최종 응답에는 싣지 않는다.

### 무엇이 저장/검증되나 (pdf2bpmn 동일)
- **저장** (`scripts/save_to_supabase.py`): `proc_def`(definition=flattened, bpmn=null) + `configuration.proc_map` + `form_def`(html+fields_json) + `users`(is_agent, 중복 재사용) + `agent_skills` + `tenants.skills`. `elements[]` → flattened 변환 포함.
- **검증** (`scripts/validate_process.py` + 벤더링한 `validation/process_validator.py`): `COMPLETION_ENGINE_URL` 의 `/initiate`·`/complete` 로 start→end 실제 실행, `bpm_proc_inst` 폴링으로 진행 확인, 결함 발견 시 LLM 으로 정의 자동 교정 후 재저장(최대 N회). 엔진 미도달 시 graceful skip.

> 필요한 env·옵션은 [../scripts/README.md](../scripts/README.md) 참조. 키는 스킬 파일에 넣지 말고 deepagent 런타임 env 상속을 사용한다.

## (대안) 프론트엔드 저장 연동

스킬 후처리를 쓰지 않을 경우의 대안. deepagent `done` content 의 출력 계약 JSON 을 프론트가 받아 저장:
- `process-gpt-vue3` `ChatRoomPage.vue` `onDone` → `ProcessGPTBackend.saveGeneratedProcessArtifacts(result)` → `proc_def`/`form_def`/`users(agent)`/`agent_skills`/`tenants.skills` persist.
- 이 경우 위 `scripts/` 후처리는 실행하지 않는다(이중 저장 방지). 둘 중 하나만 사용한다.

## 스킬 등록 (이 skill 자체를 deepagent 가 쓰게 하려면)
`ProcessGPTBackend.uploadSkills({type:'url', url})` → `/claude-skills/skills/upload-from-github` 로 이 skill 저장소를 테넌트 스킬 볼륨에 업로드(또는 `{type:'file'}` ZIP). 업로드되면 `/app/skills/<tenant>/` 에 저장되어 deepagents 가 로드한다.
