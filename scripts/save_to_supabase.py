"""스킬 서비스 실행 모드: 생성된 프로세스 정의를 Supabase에 저장한다.

pdf2bpmn 의 후처리(_save_proc_def / _save_form_def / _insert_agent_user /
_sync_skills_to_supabase / _update_proc_map)와 **동일한 결과**를 만든다.

입력: references/09-service-execution.md 의 출력 계약 JSON
  {
    "processDefinition": { ...elements[] 기반 (02-generate-definition 규격)... },
    "forms": [{ "activity_id", "form_id", "html" }],
    "agents": [{ "id","name","role","goal","persona","tools","skills":[],"activity_ids":[] }],
    "skills": ["재사용 스킬명", ...]
  }

환경변수 (deepagent 런타임에서 상속됨):
  SUPABASE_URL, SERVICE_ROLE_KEY(또는 SUPABASE_KEY/SUPABASE_ANON_KEY)
  TENANT_ID (없으면 인자/payload 사용)

사용:
  python save_to_supabase.py --input result.json --tenant <tenant_id>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# Supabase client
# --------------------------------------------------------------------------- #
def get_supabase():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_KEY_URL")
    key = (
        os.environ.get("SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SERVICE_ROLE_KEY (or SUPABASE_KEY) are required")
    return create_client(url, key)


# --------------------------------------------------------------------------- #
# elements[] -> runtime(flattened) definition
# pdf2bpmn._elements_model_to_runtime_definition 이식 (agent 필드 보존)
# --------------------------------------------------------------------------- #
def elements_to_runtime_definition(elements_model: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in (
        "megaProcessId",
        "majorProcessId",
        "processDefinitionName",
        "processDefinitionId",
        "description",
        "isHorizontal",
    ):
        if k in elements_model:
            out[k] = elements_model.get(k)

    out["data"] = elements_model.get("data") or []
    out["roles"] = elements_model.get("roles") or []
    out["events"] = []
    out["activities"] = []
    out["gateways"] = []
    out["sequences"] = []
    out["subProcesses"] = elements_model.get("subProcesses") or []
    out["participants"] = elements_model.get("participants") or []
    # DMN 은 정의 안에 그대로 보존
    if elements_model.get("dmn_decisions"):
        out["dmn_decisions"] = elements_model.get("dmn_decisions")
    if elements_model.get("dmn_rules"):
        out["dmn_rules"] = elements_model.get("dmn_rules")

    elems = elements_model.get("elements") or []
    if not isinstance(elems, list):
        return out

    def gw_type_map(t: str) -> str:
        t = (t or "").strip()
        low = t.lower()
        if low in ("exclusivegateway", "exclusive_gateway"):
            return "exclusiveGateway"
        if low in ("parallelgateway", "parallel_gateway"):
            return "parallelGateway"
        if low in ("inclusivegateway", "inclusive_gateway"):
            return "inclusiveGateway"
        return t or "exclusiveGateway"

    proc_id = out.get("processDefinitionId") or ""
    for e in elems:
        if not isinstance(e, dict):
            continue
        et = str(e.get("elementType") or "").strip().lower()
        if et == "event":
            t = str(e.get("type") or "").strip()
            if t == "StartEvent":
                rt = "startEvent"
            elif t == "EndEvent":
                rt = "endEvent"
            else:
                rt = "intermediateCatchEvent"
            out["events"].append(
                {
                    "id": e.get("id"),
                    "name": e.get("name") or "",
                    "role": e.get("role") or "",
                    "type": rt,
                    "process": proc_id,
                    "properties": "{}",
                    "description": e.get("description") or "",
                    "trigger": e.get("trigger") or "",
                }
            )
        elif et == "activity":
            dur = e.get("duration")
            out["activities"].append(
                {
                    "id": e.get("id"),
                    "name": e.get("name") or "",
                    "role": e.get("role") or "",
                    "tool": e.get("tool") or "",
                    "type": "userTask",
                    "process": proc_id,
                    "duration": int(dur) if str(dur or "").isdigit() else 5,
                    "inputData": e.get("inputData") or [],
                    "outputData": e.get("outputData") or [],
                    "properties": "{}",
                    "description": e.get("description") or "",
                    "instruction": e.get("instruction") or "",
                    "skills": e.get("skills") or [],
                    "attachedEvents": None,
                    # 스킬이 채운 agent 필드 보존 (없으면 pdf2bpmn 기본값)
                    "agent": e.get("agent"),
                    "agentMode": e.get("agentMode") or "none",
                    "orchestration": e.get("orchestration"),
                    "attachments": [],
                    "checkpoints": e.get("checkpoints") or [],
                }
            )
        elif et == "gateway":
            gw = {
                "id": e.get("id"),
                "name": e.get("name") or "",
                "role": e.get("role") or "",
                "type": gw_type_map(str(e.get("type") or "")),
                "process": proc_id,
                "condition": "",
                "properties": "{}",
                "description": e.get("description") or "",
            }
            if e.get("conditionData"):
                gw["conditionData"] = e.get("conditionData")
            out["gateways"].append(gw)
        elif et == "sequence":
            out["sequences"].append(
                {
                    "id": e.get("id"),
                    "name": e.get("name") or "",
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "condition": e.get("condition") or "",
                    "properties": e.get("properties") or "{}",
                }
            )

    return out


# --------------------------------------------------------------------------- #
# form fields extraction (프론트 extractFields 와 동등: name= 속성 수집)
# --------------------------------------------------------------------------- #
_FIELD_TAGS = (
    "text-field",
    "textarea-field",
    "boolean-field",
    "select-field",
    "checkbox-field",
    "radio-field",
    "user-select-field",
    "file-field",
    "report-field",
    "slide-field",
)


def extract_form_fields(html: str) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    if not html:
        return fields
    # <tag ... name='x' ... alias='y' ...>
    for tag in _FIELD_TAGS:
        for m in re.finditer(rf"<{tag}\b([^>]*)>", html, flags=re.IGNORECASE):
            attrs = m.group(1)
            name_m = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", attrs)
            if not name_m:
                continue
            alias_m = re.search(r"alias\s*=\s*['\"]([^'\"]+)['\"]", attrs)
            type_m = re.search(r"type\s*=\s*['\"]([^'\"]+)['\"]", attrs)
            fields.append(
                {
                    "key": name_m.group(1),
                    "name": name_m.group(1),
                    "text": alias_m.group(1) if alias_m else name_m.group(1),
                    "type": (type_m.group(1) if type_m else tag.replace("-field", "")),
                }
            )
    return fields


def compute_form_id(proc_def_id: str, activity: Dict[str, Any], form: Dict[str, Any]) -> str:
    fid = (form.get("form_id") or form.get("formId") or "").strip()
    if fid:
        return fid.replace("/", "#")
    tool = (activity.get("tool") or "").strip() if activity else ""
    if tool.startswith("formHandler:"):
        fid = tool.replace("formHandler:", "", 1).strip().replace("/", "#")
    aid = (form.get("activity_id") or form.get("activityId") or "").strip()
    if not fid or fid == "defaultform":
        fid = f"{proc_def_id}_{aid.lower()}_form"
    return fid


# --------------------------------------------------------------------------- #
# DB writes (pdf2bpmn 동일)
# --------------------------------------------------------------------------- #
def save_proc_def(sb, tenant_id: str, proc_def_id: str, name: str, definition: Dict[str, Any], bpmn=None) -> None:
    existing = sb.table("proc_def").select("id, uuid").eq("id", proc_def_id).execute()
    payload = {
        "name": name,
        "definition": definition,
        "bpmn": bpmn,
        "type": "bpmn",
        "isdeleted": False,
        "tenant_id": tenant_id,
    }
    if existing.data:
        sb.table("proc_def").update(payload).eq("uuid", existing.data[0]["uuid"]).execute()
    else:
        payload["id"] = proc_def_id
        sb.table("proc_def").insert(payload).execute()


def update_proc_map(sb, tenant_id: str, proc_def_id: str, name: str) -> None:
    res = (
        sb.table("configuration")
        .select("value")
        .eq("key", "proc_map")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    proc_map = (res.data[0].get("value") if res.data else None) or {"mega_proc_list": []}
    if not isinstance(proc_map, dict):
        proc_map = {"mega_proc_list": []}
    megas = proc_map.setdefault("mega_proc_list", [])
    mega = next((m for m in megas if m.get("id") == "unclassified" or m.get("name") == "미분류"), None)
    if not mega:
        mega = {"id": "unclassified", "name": "미분류", "major_proc_list": []}
        megas.append(mega)
    majors = mega.setdefault("major_proc_list", [])
    major = next((m for m in majors if m.get("id") == "unclassified_major" or m.get("name") == "미분류"), None)
    if not major:
        major = {"id": "unclassified_major", "name": "미분류", "sub_proc_list": []}
        majors.append(major)
    subs = major.setdefault("sub_proc_list", [])
    if not any(p.get("id") == proc_def_id for p in subs):
        subs.append({"id": proc_def_id, "name": name, "path": proc_def_id, "new": True})
    # upsert
    sb.table("configuration").upsert(
        {"key": "proc_map", "tenant_id": tenant_id, "value": proc_map},
        on_conflict="tenant_id,key",
    ).execute()


def save_form_def(sb, tenant_id, proc_def_id, activity_id, form_id, html, fields_json) -> None:
    existing = (
        sb.table("form_def")
        .select("uuid,id")
        .eq("tenant_id", tenant_id)
        .eq("proc_def_id", proc_def_id)
        .eq("activity_id", activity_id)
        .execute()
    )
    row = {
        "id": form_id,
        "html": html,
        "proc_def_id": proc_def_id,
        "activity_id": activity_id,
        "fields_json": fields_json or [],
        "tenant_id": tenant_id,
    }
    if existing.data:
        uid = existing.data[0].get("uuid")
        if uid:
            sb.table("form_def").update(row).eq("uuid", uid).execute()
        else:
            sb.table("form_def").update({"html": html, "fields_json": fields_json or []}).eq("id", form_id).execute()
    else:
        sb.table("form_def").insert(row).execute()


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or "").strip().lower())


def insert_or_reuse_agent(sb, tenant_id: str, agent: Dict[str, Any], existing: List[Dict[str, Any]]) -> Optional[str]:
    name = str(agent.get("name") or agent.get("username") or "").strip() or "자동생성 에이전트"
    role = str(agent.get("role") or "").strip()
    kn, kr = _norm(name), _norm(role)
    for u in existing:
        if kn and _norm(u.get("username")) == kn:
            return u.get("id")
        if kr and _norm(u.get("role")) == kr:
            return u.get("id")
    new_id = str(agent.get("id") or agent.get("endpoint") or uuid.uuid4())
    row = {
        "id": new_id,
        "tenant_id": tenant_id,
        "username": name,
        "role": role,
        "goal": str(agent.get("goal") or ""),
        "persona": str(agent.get("persona") or ""),
        "tools": str(agent.get("tools") or ""),
        "is_agent": True,
        "agent_type": "agent",
        "model": os.getenv("DEFAULT_NEW_AGENT_MODEL", os.getenv("LLM_MODEL", "gpt-4")),
        "alias": None,
        "endpoint": agent.get("endpoint"),
        "description": agent.get("description"),
        "skills": None,
    }
    try:
        sb.table("users").insert(row).execute()
        existing.append(row)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[WARN] users insert(agent) failed: {e}\n")
        return None
    return new_id


def sync_agent_skills(sb, tenant_id: str, user_id: str, skills: List[str]) -> None:
    skills = [str(s).strip() for s in (skills or []) if str(s).strip()]
    if not user_id or not skills:
        return
    ures = sb.table("users").select("id,skills,is_agent").eq("id", user_id).eq("tenant_id", tenant_id).execute()
    row = ures.data[0] if ures.data else None
    if not row or row.get("is_agent") is not True:
        return
    existing = [s.strip() for s in str(row.get("skills") or "").split(",") if s.strip()]
    merged = list(dict.fromkeys(existing + skills))
    sb.table("users").update({"skills": ",".join(merged)}).eq("id", user_id).eq("tenant_id", tenant_id).execute()
    for s in skills:
        try:
            sb.table("agent_skills").insert({"user_id": user_id, "tenant_id": tenant_id, "skill_name": s}).execute()
        except Exception:  # noqa: BLE001 (pk 충돌 무시)
            pass


def sync_tenant_skills(sb, tenant_id: str, skills: List[str]) -> None:
    skills = [str(s).strip() for s in (skills or []) if str(s).strip()]
    if not skills:
        return
    try:
        tres = sb.table("tenants").select("*").eq("id", tenant_id).execute()
        trow = tres.data[0] if tres.data else None
        if isinstance(trow, dict) and "skills" in trow:
            existing = [s.strip() for s in str(trow.get("skills") or "").split(",") if s.strip()]
            merged = list(dict.fromkeys(existing + skills))
            sb.table("tenants").update({"skills": ",".join(merged)}).eq("id", tenant_id).execute()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[WARN] tenants.skills sync skipped: {e}\n")


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def save_all(sb, tenant_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    pd = result.get("processDefinition") or result.get("process_definition") or result
    proc_def_id = pd.get("processDefinitionId") or pd.get("id")
    name = pd.get("processDefinitionName") or pd.get("name")
    if not proc_def_id:
        raise ValueError("processDefinitionId 누락")

    # elements[] -> flattened (pdf2bpmn proc_def.definition 규격)
    definition = elements_to_runtime_definition(pd)
    save_proc_def(sb, tenant_id, proc_def_id, name, definition, bpmn=result.get("bpmn"))
    update_proc_map(sb, tenant_id, proc_def_id, name)

    summary = {"proc_def_id": proc_def_id, "name": name, "forms": [], "agents": [], "skills": [], "definition": definition}

    # 활동 id -> 활동(tool 등) 맵 (form id 계산용)
    act_by_id = {a.get("id"): a for a in definition.get("activities", [])}

    for f in result.get("forms") or []:
        aid = f.get("activity_id") or f.get("activityId")
        html = f.get("html") or f.get("content")
        if not aid or not html:
            continue
        fid = compute_form_id(proc_def_id, act_by_id.get(aid, {}), f)
        save_form_def(sb, tenant_id, proc_def_id, aid, fid, html, extract_form_fields(html))
        summary["forms"].append(fid)

    existing_agents = (
        sb.table("users").select("id,username,role,is_agent,skills").eq("is_agent", True).eq("tenant_id", tenant_id).execute().data
    ) or []
    for a in result.get("agents") or []:
        uid = insert_or_reuse_agent(sb, tenant_id, a, existing_agents)
        if uid:
            sync_agent_skills(sb, tenant_id, uid, a.get("skills") or [])
            summary["agents"].append(uid)

    sync_tenant_skills(sb, tenant_id, result.get("skills") or [])
    summary["skills"] = result.get("skills") or []
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="service output contract JSON path")
    ap.add_argument("--tenant", default=os.environ.get("TENANT_ID"))
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    tenant_id = args.tenant or result.get("tenant_id") or "localhost"

    sb = get_supabase()
    summary = save_all(sb, tenant_id, result)
    # definition 은 검증 단계 입력으로만 쓰고 출력에서는 제외(용량)
    out = {k: v for k, v in summary.items() if k != "definition"}
    print(json.dumps({"saved": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
