"""Session-static routing to the existing, approval-bound Coding Engine."""

CODING_ENGINE_GUIDANCE = (
    "Software development in this chat uses the existing Coding Engine. "
    "For a request to create or change project code, fix a bug, add a feature or tests, "
    "call coding_task(action='start', description=<the user's complete goal>) automatically, "
    "including small programs. This must be your FIRST tool call for a development request: the engine itself inspects the project. Do not run terminal or file discovery first. Do not ask the user to choose an engine, role or tool. "
    "This workflow takes precedence over generic instructions to edit files directly. "
    "Do not implement the request using terminal, patch or write_file, and do not substitute "
    "a clarify question for the engine's fingerprint-bound approval. Read-only inspection "
    "and explanations can use ordinary read tools. If the user names an existing project, pass its exact name as project_name. Otherwise use the selected local project; if none "
    "is selected, ask which existing project to use, without guessing paths. GitHub and a "
    "PC are not prerequisites. The engine plans, asks for explicit approval, edits only an "
    "isolated worktree, runs checks and reviews the result. Follow a pending task with "
    "coding_task(action='continue'); use status to inspect it. Report actual stage, test "
    "results and failures; awaiting_keep_reject means the parent project is still unchanged. "
    "After showing test results, call coding_task(action='review_result') for the actual human Keep/Reject decision. Never substitute a separate clarify question. Keep preserves the safe copy and does not apply it to the parent. Never claim that pending work is finished. Never commit, push or merge implicitly."
)


def rewrite_development_tool(schema: dict, available: set) -> dict:
    """Place the same routing rule at the competing tool's decision point.

    Resolved by the existing dynamic-schema pass once for the session; a disabled
    engine never leaves dangling references in another tool's description.
    """
    if "coding_task" not in available:
        return schema
    fn = schema["function"]
    hint = (
        "DEVELOPMENT REQUESTS: first call coding_task(action='start', description=<complete goal>) "
        "instead of this tool, even for a small program. The Coding Engine owns discovery, "
        "repository diagnosis, edits, explicit approval and tests. Do not bypass it with "
        "direct file writes, shell scripts, Git repairs or a generic clarification approval. "
        "This tool remains available for non-development requests and read-only questions. "
    )
    return {**schema, "function": {**fn, "description": hint + fn.get("description", "")}}
