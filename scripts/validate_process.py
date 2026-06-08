"""스킬 서비스 실행 모드: 생성된 프로세스를 실행 엔진으로 검증/자동개선한다.

pdf2bpmn 의 ProcessValidator(벤더링: scripts/validation/process_validator.py)를
그대로 사용한다. pdf2bpmn._validate_generated_process 의 콜백 구성(_llm/_save/
_fetch_instance_state/_cleanup_instance)을 동일하게 주입한다.

전제(중요): process-gpt-completion 실행 엔진(/initiate·/complete) + 폴링 서비스가
떠 있고 이 스크립트(=deepagent 샌드박스)에서 HTTP 도달 가능해야 한다.
엔진에 도달 못 하면 검증은 graceful 하게 건너뛴다.

환경변수:
  SUPABASE_URL, SERVICE_ROLE_KEY(또는 SUPABASE_KEY)
  COMPLETION_ENGINE_URL            (예: http://process-gpt-completion:8000) — 없으면 검증 skip
  PDF2BPMN_VALIDATION_ENABLED      (기본 true)
  PDF2BPMN_VALIDATION_MAX_ITERS    (기본 5)
  PDF2BPMN_VALIDATION_ADVANCE_TIMEOUT (기본 70)
  PDF2BPMN_VALIDATION_CLEANUP      (기본 false — 검증 인스턴스 보존)
  VALIDATION_ACTOR_EMAIL           (선택)
  # LLM (OpenAI 호환)
  LLM_MODEL / VALIDATION_LLM_MODEL, LLM_PROXY_URL(or OPENAI_BASE_URL),
  LLM_PROXY_API_KEY(or OPENAI_API_KEY)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validation import ProcessValidator  # noqa: E402


def _truthy(v: Optional[str], default: bool) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# LLM (OpenAI 호환) — 검증기가 기대하는 "messages -> 파싱된 JSON dict" 콜백
# --------------------------------------------------------------------------- #
def _make_llm_call():
    model = os.environ.get("VALIDATION_LLM_MODEL") or os.environ.get("LLM_MODEL") or "gpt-4o"
    # "anthropic:claude-..." 같은 prefix 는 OpenAI 호환 프록시에 맞게 정리
    if ":" in model and model.split(":", 1)[0] in ("anthropic", "openai", "google"):
        model = model.split(":", 1)[1]
    base_url = os.environ.get("LLM_PROXY_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("LLM_PROXY_API_KEY") or os.environ.get("OPENAI_API_KEY")

    async def _llm(messages: List[Dict[str, Any]], max_tokens: int) -> Optional[dict]:
        try:
            from openai import AsyncOpenAI
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[VALIDATION] openai SDK 없음: {e}\n")
            return None
        client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except Exception:
            # response_format 미지원 프록시 폴백
            resp = await client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.0
            )
        text = (resp.choices[0].message.content or "").strip()
        return _parse_json(text)

    return _llm


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    import re

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# DB 콜백 (pdf2bpmn 동일)
# --------------------------------------------------------------------------- #
def _make_callbacks(sb, tenant_id: str):
    async def _save_definition(pdid: str, definition: Dict[str, Any]) -> bool:
        try:
            existing = sb.table("proc_def").select("uuid").eq("id", pdid).eq("tenant_id", tenant_id).execute()
            if existing.data:
                sb.table("proc_def").update({"definition": definition}).eq("uuid", existing.data[0]["uuid"]).execute()
            else:
                sb.table("proc_def").update({"definition": definition}).eq("id", pdid).execute()
            return True
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[VALIDATION] save_definition 실패: {e}\n")
            return False

    def _fetch_state_sync(proc_inst_id: str) -> Dict[str, Any]:
        rows = (
            sb.table("bpm_proc_inst")
            .select("proc_inst_id,status,current_activity_ids")
            .or_(f"proc_inst_id.eq.{proc_inst_id},root_proc_inst_id.eq.{proc_inst_id}")
            .eq("tenant_id", tenant_id)
            .execute()
            .data
        ) or []
        status = "RUNNING"
        active: List[str] = []
        for row in rows:
            cids = row.get("current_activity_ids") or []
            if isinstance(cids, str):
                cids = [cids]
            if row.get("proc_inst_id") == proc_inst_id:
                status = row.get("status") or "RUNNING"
                active.extend(str(c) for c in cids if c)
            elif str(row.get("status") or "").upper() == "RUNNING":
                active.extend(str(c) for c in cids if c)
        return {"status": status, "current_activity_ids": list(dict.fromkeys(active))}

    async def _fetch_instance_state(proc_inst_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(_fetch_state_sync, proc_inst_id)

    cleanup_enabled = _truthy(os.environ.get("PDF2BPMN_VALIDATION_CLEANUP"), False)

    def _cleanup_sync(proc_inst_id: str) -> None:
        for table in ("todolist", "bpm_proc_inst"):
            try:
                sb.table(table).delete().or_(
                    f"proc_inst_id.eq.{proc_inst_id},root_proc_inst_id.eq.{proc_inst_id}"
                ).eq("tenant_id", tenant_id).execute()
            except Exception:
                pass

    async def _cleanup_instance(proc_inst_id: str) -> None:
        if not cleanup_enabled:
            return
        await asyncio.to_thread(_cleanup_sync, proc_inst_id)

    return _save_definition, _fetch_instance_state, _cleanup_instance


async def validate(sb, tenant_id: str, proc_def_id: str, process_name: str,
                   proc_json: Dict[str, Any], forms: Dict[str, Any]) -> Dict[str, Any]:
    if not _truthy(os.environ.get("PDF2BPMN_VALIDATION_ENABLED"), True):
        return {"proc_def_id": proc_def_id, "skipped": True, "passed": None,
                "skip_reason": "검증 비활성화(PDF2BPMN_VALIDATION_ENABLED=false)"}
    engine = os.environ.get("COMPLETION_ENGINE_URL")
    if not engine:
        return {"proc_def_id": proc_def_id, "skipped": True, "passed": None,
                "skip_reason": "COMPLETION_ENGINE_URL 미설정 — 실행 검증 불가"}

    save_def, fetch_state, cleanup = _make_callbacks(sb, tenant_id)
    validator = ProcessValidator(
        llm_call=_make_llm_call(),
        save_definition=save_def,
        engine_base_url=engine,
        tenant_id=tenant_id,
        fetch_instance_state=fetch_state,
        cleanup_instance=cleanup,
        max_iters=int(os.environ.get("PDF2BPMN_VALIDATION_MAX_ITERS") or 5),
        advance_timeout=float(os.environ.get("PDF2BPMN_VALIDATION_ADVANCE_TIMEOUT") or 70.0),
        actor_email=os.environ.get("VALIDATION_ACTOR_EMAIL"),
    )
    return await validator.validate_and_repair(
        proc_def_id=proc_def_id, process_name=process_name, proc_json=proc_json, forms=forms,
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--proc-json", required=True, help="flattened definition JSON path (save_all 산출 definition)")
    ap.add_argument("--forms", help="forms map JSON path { form_id: {fields_json:[...]} }", default=None)
    ap.add_argument("--tenant", default=os.environ.get("TENANT_ID") or "localhost")
    args = ap.parse_args()

    with open(args.proc_json, "r", encoding="utf-8") as fh:
        proc_json = json.load(fh)
    forms = {}
    if args.forms and os.path.exists(args.forms):
        with open(args.forms, "r", encoding="utf-8") as fh:
            forms = json.load(fh)

    from save_to_supabase import get_supabase

    sb = get_supabase()
    proc_def_id = proc_json.get("processDefinitionId") or proc_json.get("id")
    name = proc_json.get("processDefinitionName") or proc_json.get("name") or proc_def_id
    report = asyncio.run(validate(sb, args.tenant, proc_def_id, name, proc_json, forms))
    slim = {k: report.get(k) for k in ("proc_def_id", "passed", "skipped", "skip_reason",
                                       "iterations", "repaired", "remaining_defects")}
    print(json.dumps({"validation": slim}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
