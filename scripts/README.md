# scripts — 서비스 실행 모드 후처리 (저장 + 검증)

deepagent(process-gpt-deepagents) 런타임에서 이 스킬이 프로세스를 생성한 뒤,
**pdf2bpmn 와 동일한 후처리(Supabase 저장 + 실행 검증)** 를 수행하는 스크립트 모음입니다.
대화형(Claude Code) 모드에서는 쓰지 않습니다 — 서비스 모드 전용.

## 구성

| 파일 | 역할 |
|------|------|
| `run_postprocess.py` | **단일 진입점.** 결과 JSON 하나로 저장→검증을 한 번에 수행 |
| `save_to_supabase.py` | `proc_def`/`form_def`/`users(agent)`/`agent_skills`/`tenants.skills` 저장 (pdf2bpmn `_save_*`/`_insert_agent_user`/`_sync_skills` 이식). `elements[]`→flattened 변환 포함 |
| `validate_process.py` | process-gpt-completion `/initiate`·`/complete` 로 start→end 실행 검증 + LLM 자동개선 래퍼 |
| `validation/process_validator.py` | pdf2bpmn `ProcessValidator` **벤더링**(원본 그대로, 의존성 주입형) |
| `requirements.txt` | `supabase`, `httpx`, `openai` |

## 실행 (deepagent 샌드박스)

```bash
pip install -r requirements.txt
python run_postprocess.py --input result.json --tenant <tenant_id>
# 검증 생략: --no-validate
```

`result.json` 은 [../references/09-service-execution.md](../references/09-service-execution.md) 의
**출력 계약 JSON**(processDefinition / forms / agents / skills) 입니다.

## 환경변수

| 변수 | 용도 | 필수 |
|------|------|------|
| `SUPABASE_URL` | Supabase URL | ✅ 저장 |
| `SERVICE_ROLE_KEY` (또는 `SUPABASE_KEY`) | service-role 키 | ✅ 저장 |
| `TENANT_ID` | 테넌트(인자로도 전달 가능) | 권장 |
| `COMPLETION_ENGINE_URL` | process-gpt-completion 베이스 URL | 검증 시 필수(없으면 검증 skip) |
| `PDF2BPMN_VALIDATION_ENABLED` | 기본 true | — |
| `PDF2BPMN_VALIDATION_MAX_ITERS` | 기본 5 | — |
| `PDF2BPMN_VALIDATION_ADVANCE_TIMEOUT` | 기본 70초 | — |
| `PDF2BPMN_VALIDATION_CLEANUP` | 기본 false(검증 인스턴스 보존) | — |
| `LLM_MODEL`/`VALIDATION_LLM_MODEL`, `LLM_PROXY_URL`/`OPENAI_BASE_URL`, `LLM_PROXY_API_KEY`/`OPENAI_API_KEY` | 검증 자동개선 LLM(OpenAI 호환) | 검증 시 |

> 키는 **deepagent 런타임 env 에서 상속**됩니다(`sandbox_*` 가 `merged_env=dict(os.environ)`). 스킬 파일에 키를 넣지 마세요.

## 출력

`run_postprocess.py` 는 다음 JSON 을 stdout 으로 출력합니다(에이전트가 사용자 보고에 사용):

```json
{
  "saved": { "proc_def_id": "...", "name": "...", "forms": ["..."], "agents": ["..."], "skills": ["..."] },
  "validation": { "passed": true, "skipped": false, "iterations": 2, "repaired": true, "remaining_defects": [] }
}
```

## 주의

- 저장 정의 형태: pdf2bpmn 와 동일하게 **flattened**(`activities/events/gateways/sequences`)로 `proc_def.definition` 에 저장합니다. (스킬은 `elements[]` 로 생성 → 스크립트가 변환)
- 검증은 **process-gpt-completion 실행 엔진 + 폴링 서비스가 떠 있고** 샌드박스에서 HTTP 도달 가능할 때만 동작합니다. 도달 못 하면 graceful skip.
- 검증은 테스트용 인스턴스(`bpm_proc_inst`/`todolist`)를 생성합니다(기본 보존, `PDF2BPMN_VALIDATION_CLEANUP=true` 시 삭제).
