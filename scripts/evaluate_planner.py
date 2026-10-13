"""Validate fictional evaluation fixtures; --live explicitly calls configured AI."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_cases(cases):
    assert len(cases) == 20, "Expected 20 evaluation cases"
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert 10 <= len(case["description"]) <= 5000
        assert len(case.get("current_event_context", "")) <= 5000
        assert len(case.get("history", "")) <= 3000
        assert case["human_checks"]


def findings(case, draft):
    # These are narrow mechanical checks. Task quality and source conflicts
    # require the separate human rubric; a green result is not a quality score.
    body = draft.model_dump(mode="json")
    searchable = json.dumps(body, ensure_ascii=False)
    violations = [f"出现应排除内容：{term}" for term in case.get("forbidden", []) if term in searchable]
    if case.get("no_deadlines") and (draft.item.deadline is not None or any(t.deadline is not None for t in draft.tasks)):
        violations.append("没有可靠时间背景却生成了截止日期")
    if not case.get("history") and draft.suggestions:
        violations.append("没有历史知识依据却生成了可能遗漏建议")
    return violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make exactly one provider request per case (20 total), using synthetic data only")
    parser.add_argument("--output", type=Path, default=Path("planner-evaluation-report.json"))
    parser.add_argument("--drafts-directory", type=Path, help="Optional private directory for synthetic drafts needed for human review")
    args = parser.parse_args()
    cases = json.loads((ROOT / "docs/fixtures/planner-evaluation.json").read_text())
    validate_cases(cases)
    if not args.live:
        print("20 fictional AI evaluation cases validated; live model quality has NOT been tested.")
        return 0
    sys.path.insert(0, str(ROOT / "backend"))
    from app.ai_planner import get_planner_provider, provider_is_configured
    if not provider_is_configured():
        parser.error("Live evaluation requires server-side provider configuration; no requests were made")
    if args.drafts_directory:
        directory = args.drafts_directory.resolve()
        if directory.is_relative_to(ROOT):
            parser.error("Draft directory must be outside the public repository")
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    provider = get_planner_provider()
    results = []
    for case in cases:
        sections = ["【负责人描述】\n" + case["description"]]
        if case.get("current_event_context"):
            sections.append("【本次事项资料】\n" + case["current_event_context"])
        if case.get("history"):
            sections.append("【团队历史经验】\n" + case["history"])
        try:
            generation = provider.generate("\n\n".join(sections))
            if args.drafts_directory:
                draft_path = directory / (case["id"] + ".json")
                draft_path.write_text(generation.draft.model_dump_json(indent=2))
                draft_path.chmod(0o600)
            results.append({"id": case["id"], "automated_violations": findings(case, generation.draft), "human_review": "pending", "human_checks": case["human_checks"], "task_count": len(generation.draft.tasks), "total_tokens": generation.total_tokens})
        except Exception as error:
            # Only the exception type is saved, never SDK messages or keys.
            results.append({"id": case["id"], "provider_error": type(error).__name__, "human_review": "pending"})
    report = {"mode": "live", "request_actions": len(cases), "data": "fictional fixtures only", "results": results}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    args.output.chmod(0o600)
    print(f"20 request actions completed; report: {args.output}; human semantic review still required.")
    return int(any(r.get("provider_error") or r.get("automated_violations") for r in results))


if __name__ == "__main__":
    sys.exit(main())
