# 09 – 실행 모델: 샌드박스 파일 기반 5단계 + 검증 + 생성 완료 안내

이 skill 은 **항상 동일한 단일 5단계**로 동작한다(대화형/서비스 모드 구분 없음). 모든 산출물은 **대화 컨텍스트가 아니라 샌드박스 작업 파일**로 만들고, 전용 **도구**로 검증·전달한다. **DB 에 직접 쓰지 않는다(읽기 전용)** — 저장은 사용자가 프론트 '저장' 버튼을 누를 때 프론트가. 스킬도 workspace 파일 산출물로만 둔다(외부 업로드·저장 없음).

> 🔁 **단일 세션 실행(필수)**: 한 연속 실행으로 5단계를 끝까지 간다. **사용자 확인(HITL)은 오직 `request_human_input`(interrupt)로만** 한다(프로즈로 응답을 끝내지 말 것 — 턴이 끊겨 새 실행이 되고 순서가 꼬인다). 멈춤은 **정확히 2곳**: 1단계 컨설팅 승인, 2단계 후보 선택. 그 사이/이후는 멈추지 말고 자동 진행한다.

---

## 샌드박스 작업 파일 (컨테이너 `/workspace/.bpmn/`)

- `process-definition.json` — **elements[] 형식**(02-generate-definition 규격) processDefinition. 1단계 `write_file` 생성 → 2·3단계 `edit_file` 업데이트 → 4단계 검증이 교정해 다시 씀.
- `skills/<safe-name>/SKILL.md` — 2단계 skill-creator 산출(workspace 파일 산출물, 업로드 없음).
- `forms/<activity_id>.html` — 3단계 폼(7단계 컴포넌트 규격).
- `agents.json` — 2단계 에이전트 프로필 배열(없으면 생략).
- (문서 업로드 시) `/workspace/uploads/<파일>` — executor 가 실행 전 주입. `read_file` 로 직접 읽는다.

> 경로는 항상 **`/workspace/.bpmn/...`** 절대경로로 쓴다(`/bpmn/...` 아님). 파일은 실제 샌드박스 FS 에 쓰이고 호스트 도구가 같은 파일을 읽는다.

---

## 5단계

### 1. 컨설팅 & 프로세스 JSON 생성
- 문서 업로드면 `/workspace/uploads/<파일>` 을 `read_file`/Read 로 **직접 읽어** as-is 흐름을 파악한다([10-document-intake.md](10-document-intake.md)).
- 컨설팅 초안을 **`request_human_input`** 으로 제시·승인받는다([01-consulting.md](01-consulting.md)).
- 승인 흐름을 [02-generate-definition.md](02-generate-definition.md) 규격의 **elements[] JSON** 으로 만들어 `write_file` 로 `/workspace/.bpmn/process-definition.json` 에 쓴다. **반드시 실제 elements(StartEvent·EndEvent·UserActivity·Sequence 등)를 채운다**(placeholder/빈 elements 금지). 흐름 연결은 **Sequence 요소(source/target)** 로 표현한다.

### 2. 스킬·에이전트·DMN 후보 선택 & 생성 (산출물 파일)
- elements 에서 구체 후보를 도출해(규칙: [03-elicit-artifacts.md](03-elicit-artifacts.md)) **`request_human_input`** 으로 묻는다. 후보는 `question` 인자에 `[스킬]`/`[에이전트]`/`[DMN]`(대괄호만) + `• 라벨: 설명` 으로 나열한다(모호어 '자동화 요소' 금지, 빈 질문 금지).
- 선택분만:
  - **스킬**: `skill-creator` 로 `/workspace/.bpmn/skills/<safe-name>/SKILL.md` 생성([04-skills.md](04-skills.md)) — workspace 파일 산출물로만 둔다(업로드·저장 없음).
  - **에이전트**: 프로필을 `/workspace/.bpmn/agents.json` 배열로([05-agents.md](05-agents.md)).
  - **DMN**: `dmn_decisions`/`dmn_rules` 를 process-definition.json 안에([06-dmn.md](06-dmn.md)).
  - `edit_file` 로 process-definition.json 의 `activity.skills`/`activity.agent`/`agentMode`/`orchestration` 반영.

### 3. 폼 · 참조정보 (자동, 질문 없음)
- 각 UserActivity 폼을 `/workspace/.bpmn/forms/<activity_id>.html` 로 만든다([07-forms.md](07-forms.md)).
- 참조정보(`activity.inputData`, gateway `conditionData`)를 process-definition.json 에 반영([08-reference-info.md](08-reference-info.md)).

### 4. 검증 & 자동개선 (최대 5회)
- **`validate_process_definition()`** 도구를 호출한다. 도구가 흐름 결함(끊긴 시퀀스, startEvent 도달불가, endEvent 미연결, 게이트웨이 없는 분기 등)을 검사하고 결함이 있으면 최대 5회 자동개선해 같은 파일에 다시 쓴다(실엔진·DB 없음).
- 반환이 `passed:false` 면 `remaining_defects` 를 보고 `edit_file` 로 직접 더 고친 뒤 다시 호출한다.

### 5. 생성 완료 안내 (프론트 전달)
- **`complete_process_generation()`** 도구를 호출한다(인자 없음). 도구가 `/workspace/.bpmn/` 의 산출물(process-definition.json + forms + agents.json + skills)을 모아 **출력계약으로 프론트에 전달**한다. **작업 파일은 보존**한다(자동 삭제 없음 — 산출물 전용).
- 그 뒤 채팅엔 **"프로세스를 생성했어요. 확인 후 저장 버튼을 눌러주세요."** 정도만 남긴다. **JSON 을 채팅에 덤프하지 않는다.**

---

## 역할 분담 (중요)
- **에이전트(이 스킬)**: 산출물을 샌드박스 파일로 만들고, 검증하고, `complete_process_generation` 으로 프론트에 전달한다. **DB 에 쓰지 않는다.**
- **스킬**: `/workspace/.bpmn/skills/<name>/SKILL.md` 파일 산출물로만 둔다(외부 업로드·등록 없음 — 사용자가 프론트에서 확인/저장).
- **프론트(process-gpt-vue3)**: 전달받은 산출물을 **ArtifactPanel(우측 산출물 사이드바)** 에 결과로 띄우고 '저장' 버튼을 제공한다. 사용자가 저장을 누르면 그때 proc_def/form_def 를 **사용자 권한으로** 저장한다(미리보기는 저장 전 createBpmnXml 변환으로 표시).

## 출력계약 형식 (complete 가 조립해 전달 — 참고)
```json
{ "type": "process-definition-result",
  "processDefinition": { "processDefinitionId": "...(자동 UUID)", "processDefinitionName": "...",
                         "elements": [ ... ], "roles": [ ... ], "dmn_decisions": [...], "dmn_rules": [...] },
  "forms": [ { "activity_id": "...", "form_id": "...", "html": "<section>...</section>" } ],
  "agents": [ { "name": "...", "role": "...", "skills": ["..."], "activity_ids": ["..."] } ],
  "skills": ["..."] }
```
- `processDefinitionId` 는 complete 도구가 **항상 랜덤 UUID** 로 채운다.
- 저장 시 프론트가 elements[] → flattened 변환 후 proc_def 에 저장한다.
