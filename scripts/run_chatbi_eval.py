import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.chatbi.parser import parse_with_context


def subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(subset(item, candidate) for candidate in actual) for item in expected)
    return expected == actual


def evaluate_case(case: dict) -> tuple[bool, str, dict]:
    plan = parse_with_context(case["question"], case.get("conversation_context", []))
    actual = plan.model_dump(mode="json")
    expected = case.get("expected_query_plan")
    if expected is not None:
        passed = subset(expected, actual)
        return passed, "expected_query_plan subset matched" if passed else "query plan mismatch", actual
    prefix = case["case_id"].split("-")[0]
    if prefix == "CLAR":
        passed = plan.status == "needs_clarification"
    elif prefix == "DATA":
        passed = plan.status in {"needs_clarification", "rejected"}
    elif prefix == "SEC":
        passed = plan.status == "rejected" or (case["case_id"] == "SEC-004" and any(item.field == "region" and item.value == "区域B" for item in plan.filters))
    elif prefix == "MEM":
        passed = plan.status in {"needs_clarification", "rejected"}
    elif case["case_id"] == "CTX-005":
        passed = plan.status == "needs_clarification"
    else:
        passed = plan.status != "ready"
    return passed, "safe behavior matched" if passed else "safe behavior mismatch", actual


def main() -> None:
    source_path = ROOT / "tests" / "evaluation" / "chatbi_evaluation_set_v0.1.json"
    output_dir = ROOT / "tests" / "evaluation" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    results = []
    for case in source["cases"]:
        passed, reason, actual = evaluate_case(case)
        results.append({"case_id": case["case_id"], "passed": passed, "reason": reason, "actual_query_plan": actual})
    passed_count = sum(item["passed"] for item in results)
    report = {
        "evaluation_set": source["name"], "evaluation_version": source["version"],
        "query_plan_version": "0.1.0", "executed_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results), "passed": passed_count, "failed": len(results) - passed_count,
        "pass_rate": round(passed_count / len(results), 4), "hardcoded_answers": False,
        "results": results,
    }
    (output_dir / "chatbi_eval_v0.1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed_ids = [item["case_id"] for item in results if not item["passed"]]
    markdown = f"# ChatBI 固定评测报告 v0.1\n\n- 总数：{len(results)}\n- 通过：{passed_count}\n- 失败：{len(failed_ids)}\n- 通过率：{report['pass_rate']:.2%}\n- 失败用例：{', '.join(failed_ids) if failed_ids else '无'}\n- 评测边界：Query Plan 子集、澄清/拒绝和安全行为；经营数字正确性由指标与集成测试覆盖。\n"
    (output_dir / "chatbi_eval_v0.1.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"total": len(results), "passed": passed_count, "failed": len(failed_ids), "failed_ids": failed_ids}, ensure_ascii=False))
    raise SystemExit(0 if not failed_ids else 1)


if __name__ == "__main__":
    main()
