"""Result review through the existing human-input callback, never model arguments."""
from __future__ import annotations

import hashlib
import json

KEEP = "Διατήρηση στο ασφαλές αντίγραφο — χωρίς αλλαγή στο αρχικό έργο"
REJECT = "Απόρριψη αποτελέσματος — χωρίς αλλαγή στο αρχικό έργο"


def result_fingerprint(view: dict) -> str:
    payload = {key: view[key] for key in ("task_id", "project", "result")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def ask_result_choice(view: dict, callback) -> str:
    from tools.clarify_tool import clarify_tool

    result = view["result"]
    tests = "; ".join(f"{t['check']}: {t['status']}" for t in result.get("tests", []))
    question = (
        f"Αξιολόγηση αποτελέσματος {view['task_id']}\nΈργο: {view['project']}\n"
        f"Αρχεία: {', '.join(result['changed_files'])}\nΈλεγχοι: {tests}\n"
        f"Τελικός έλεγχος: {result['reviewer_verdict']}\n"
        f"Αποτύπωμα αποτελέσματος: {result_fingerprint(view)}\n"
        "Η διατήρηση κρατά τις αλλαγές στο ασφαλές αντίγραφο για συνέχεια. "
        "Η απόρριψη χρησιμοποιεί την ασφαλή διαδικασία του Engine, με αρχείο ανάκτησης όπου προβλέπεται. "
        "Το αρχικό έργο παραμένει ανέπαφο. Χωρίς commit, push ή merge. "
        "Η διακοπή αφήνει το αποτέλεσμα σε αναμονή."
    )
    # Existing qids are opaque wire identities. A trusted namespace lets clients
    # preserve read-only policy for this mutating choice without a new protocol.
    qid = f"coding-result:{view['task_id']}:{result_fingerprint(view)}"
    def bound_callback(questions):
        reply = callback([{**questions[0], "qid": qid}])
        answers = reply.get("answers") or {}
        return {**reply, "answers": {"q0": answers.get(qid)}}
    reply = json.loads(clarify_tool([{"question": question, "choices": [KEEP, REJECT]}],
                                  callback=bound_callback if callback is not None else None))
    responses = reply.get("responses") or []
    if reply.get("outcome") != "submitted" or len(responses) != 1:
        return "unanswered"
    response = responses[0]
    if response.get("status") != "answered":
        return "unanswered"
    return {KEEP: "keep", REJECT: "reject"}.get(response.get("user_response"), "unanswered")
