"""스킬 서비스 실행 모드: 생성 결과 JSON 하나로 저장→검증을 한 번에 수행한다.

deepagent 샌드박스에서 에이전트가 호출하는 단일 진입점.

흐름:
  1) result.json(09-service-execution.md 출력 계약) 로드
  2) save_to_supabase.save_all  → proc_def / form_def / users(agent) / agent_skills / tenants.skills
  3) (옵션) validate_process.validate → process-gpt-completion /initiate·/complete 실행 검증 + 자동개선
  4) 통합 요약 JSON 을 stdout 으로 출력 (에이전트가 사용자에게 보고)

사용:
  python run_postprocess.py --input result.json --tenant <tenant_id> [--no-validate]

필요 패키지: pip install -r requirements.txt   (supabase, httpx, openai)
환경변수: save_to_supabase.py / validate_process.py docstring 참조.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from save_to_supabase import get_supabase, save_all, extract_form_fields, compute_form_id  # noqa: E402
import validate_process  # noqa: E402


def _build_forms_map(result: dict, definition: dict, proc_def_id: str) -> dict:
    """검증기 입력용 forms map: { form_id: {form_id, fields_json:[...]} }."""
    act_by_id = {a.get("id"): a for a in definition.get("activities", [])}
    forms_map = {}
    for f in result.get("forms") or []:
        aid = f.get("activity_id") or f.get("activityId")
        html = f.get("html") or f.get("content")
        if not aid or not html:
            continue
        fid = compute_form_id(proc_def_id, act_by_id.get(aid, {}), f)
        forms_map[fid] = {"form_id": fid, "fields_json": extract_form_fields(html)}
    return forms_map


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="service output contract JSON path")
    ap.add_argument("--tenant", default=os.environ.get("TENANT_ID"))
    ap.add_argument("--no-validate", action="store_true", help="검증 단계 건너뜀")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    tenant_id = args.tenant or result.get("tenant_id") or "localhost"

    sb = get_supabase()

    # 1) 저장
    saved = save_all(sb, tenant_id, result)
    definition = saved.pop("definition")  # 검증 입력용(요약 출력에서는 제외)
    out = {"saved": saved}

    # 2) 검증 (옵션 / 엔진 있을 때만)
    if not args.no_validate:
        proc_def_id = saved["proc_def_id"]
        forms_map = _build_forms_map(result, definition, proc_def_id)
        try:
            report = asyncio.run(
                validate_process.validate(
                    sb, tenant_id, proc_def_id, saved.get("name") or proc_def_id, definition, forms_map
                )
            )
            out["validation"] = {
                k: report.get(k)
                for k in ("passed", "skipped", "skip_reason", "iterations", "repaired", "remaining_defects")
            }
        except Exception as e:  # noqa: BLE001
            out["validation"] = {"passed": None, "skipped": True, "skip_reason": f"검증 예외(무시): {e}"}

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
