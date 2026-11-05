"""Opt-in live inference rehearsal, with synthetic input and a fresh isolated profile.

Uses the selected provider's existing credential in memory. Never copies .env,
auth files, personal memory or chats. It makes billable provider calls; it is not
part of ordinary CI. Run from the repository root with the managed Python.
"""
import argparse
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def runtime_from(home):
    from agent.secret_scope import build_profile_secret_scope, set_secret_scope
    from hermes_cli.config import load_config_readonly
    from hermes_cli.runtime_provider import resolve_runtime_provider

    os.environ["HERMES_HOME"] = str(home)
    secrets = build_profile_secret_scope(home)
    set_secret_scope(secrets, profile_home=str(home))
    config = load_config_readonly()
    model = config.get("model") or {}
    runtime = resolve_runtime_provider(requested=model.get("provider"), target_model=model.get("default"))
    return runtime, model, config.get("delegation") or {}


def make_agent(runtime, model, root, session, *, tools):
    from run_agent import AIAgent
    return AIAgent(
        **{key: runtime.get(key) for key in ("provider", "base_url", "api_key", "api_mode")},
        model=model, cwd=str(root), session_id=session, enabled_toolsets=tools,
        max_iterations=10, max_tokens=4000, run_budget_seconds=150,
        quiet_mode=True, skip_context_files=True, skip_memory=True,
        skip_background_review=True, save_trajectories=False,
        reasoning_config={"effort": "low"}, fallback_model=None,
    )


def task(key, workload, filename, goal, acceptance):
    return {"id": key, "goal": goal, "workload": workload, "acceptance": acceptance,
            "write_paths": [filename] if filename else [], "parallel_safe": True,
            "tool_access": "files_only"}


def project(parent, action, **args):
    from model_tools import handle_function_call
    result = json.loads(handle_function_call("coordinate_project", {
        "action": action, "project": "live-payments", **args,
    }, parent_agent=parent))
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def wait_settled(parent):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        result = project(parent, "status")
        if not any(row["state"] == "running" for row in result["tasks"].values()):
            return result
        time.sleep(0.2)
    raise TimeoutError("Live Coordinator helpers did not settle within the rehearsal budget")


def verify_outputs(root):
    with (root / "payments.csv").open(encoding="utf-8", newline="") as stream:
        expected = [{"id": r["id"], "cents": int(r["cents"])} for r in csv.DictReader(stream)]
    rows = json.loads((root / "rows.json").read_text(encoding="utf-8-sig"))
    report = json.loads((root / "report.json").read_text(encoding="utf-8-sig"))
    if rows != expected or report != {"net_cents": 1200, "unique_payments": 2}:
        raise AssertionError({"expected_rows": expected, "actual_rows": rows, "actual_report": report})


def rehearse(directory, runtime, model):
    from hermes_cli.plugins import PluginManager
    from tools import delegate_tool
    from tools.terminal_tool import record_session_cwd

    root = directory / "project"
    root.mkdir()
    (root / "payments.csv").write_text("id,cents\np1,1000\np1,1000\np2,500\nr1,-300\n", encoding="utf-8")
    parent = make_agent(runtime, model, root, "live-coordinator", tools=["file", "delegation"])
    other = make_agent(runtime, model, root, "live-other-chat", tools=[])
    parent._current_task_id = "live-project-driver"
    manager = PluginManager()
    events = []
    build = delegate_tool._build_child_preserving_parent_tools

    def instrumented(**kwargs):
        child = build(**kwargs)
        events.append({"model": child.model, "provider": child.provider,
                       "built_at": time.monotonic()})
        return child

    delegate_tool._build_child_preserving_parent_tools = instrumented
    manager.discover_and_load()
    try:
        record_session_cwd(parent._current_task_id, str(root))
        plan = [
            task("normalize", "routine", "rows.json",
                 "Read payments.csv and write rows.json as an array of objects with id:string and cents:integer. "
                 "Retain every row in original order, including duplicates. Use write_file, then read back.",
                 "Every original row, including the duplicate, is retained; cents are integers."),
            task("reconcile", "complex", "report.json",
                 "Read payments.csv. Keep the first occurrence of each id; sum signed cents including refunds. "
                 "Write report.json with exactly net_cents and unique_payments. unique_payments counts positive "
                 "payment ids, excluding refunds. Read back and check arithmetic.",
                 "Deduplicate p1, include r1 refund: net_cents=1200 and unique_payments=2."),
        ]
        project(parent, "create", root=str(root), tasks=plan)
        started = time.monotonic()
        dispatched = project(parent, "run")
        if dispatched.get("dispatch", {}).get("status") != "dispatched":
            raise AssertionError("An interactive probe must actually dispatch detached helpers")
        active = project(parent, "status")
        overlap = any(row["state"] == "running" for row in active["tasks"].values())
        if not overlap:
            raise AssertionError("Helpers finished before the concurrent-chat probe began")
        with ThreadPoolExecutor(max_workers=1) as pool:
            other_run = pool.submit(copy_context().run, other.run_conversation,
                                    "Synthetic smoke check: what is 7 plus 8? Reply with just the integer.")
            settled = wait_settled(parent)
            answer = other_run.result(timeout=180)
        if any(row["state"] != "needs_review" for row in settled["tasks"].values()):
            raise AssertionError(settled)
        if "15" not in str(answer.get("final_response", "")):
            raise AssertionError("Independent live chat did not answer correctly")
        verify_outputs(root)
        for key, filename in (("normalize", "rows.json"), ("reconcile", "report.json")):
            project(parent, "verify", task=key, attempt=1, passed=True, artifacts=[filename],
                    evidence="Independent Python checks compared every CSV row and exact reconciled totals.")
        final = project(parent, "status")
        if not final["complete"] or {event["provider"] for event in events} != {runtime["provider"]}:
            raise AssertionError("Project acceptance/provider pin failed")
        return {"schema": 1, "provider": runtime["provider"], "parent_model": model,
                "helper_models": [e["model"] for e in events], "detached": True,
                "other_chat_submitted_during_project": overlap,
                "independent_chat_passed": True, "artifacts_verified": True,
                "complete": final["complete"], "elapsed_seconds": round(time.monotonic() - started, 2),
                "tasks": {key: {"state": row["state"], "attempt": row["attempt"],
                                 "api_calls": row.get("result", {}).get("api_calls")}
                          for key, row in final["tasks"].items()}}
    finally:
        delegate_tool._build_child_preserving_parent_tools = build
        manager.unload()
        parent.close()
        other.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="A new directory; existing paths are refused")
    parser.add_argument("--bash", type=Path, help="Existing managed bash for a source-checkout rehearsal on Windows")
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    if args.bash:
        if not args.bash.is_file():
            parser.error("--bash must identify an existing executable")
        os.environ["HERMES_GIT_BASH_PATH"] = str(args.bash.resolve())
    runtime, model, delegation = runtime_from(args.credential_home.resolve())
    home = directory / "profile"
    home.mkdir()
    import hermes_yaml as yaml
    config = {"model": {"provider": runtime["provider"], "default": model["default"]},
              "delegation": {"backend": delegation.get("backend", "meu_coordinator_general"),
                             "models": delegation.get("models", {}), "max_iterations": 10},
              "terminal": {"backend": "local"}, "memory": {"enabled": False}}
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    os.environ.update(HERMES_HOME=str(home), MEU_HOME=str(home), MEU_AGENT_MODE="1")
    from hermes_constants import set_hermes_home_override
    from agent.secret_scope import set_secret_scope
    set_hermes_home_override(home)
    # The fixed selected credential is carried by the runtime only. Do not
    # expose the source profile's other credentials to this isolated session.
    set_secret_scope({}, profile_home=str(home))
    result = rehearse(directory, runtime, model["default"])
    (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
