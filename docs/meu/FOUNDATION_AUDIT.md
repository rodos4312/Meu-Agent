# Meu Agent — Foundation Audit and Engineering Gates

Status: foundation in development. The initial reconnaissance below is historical; see the dated privacy verification at the end. This is not a security certification or a release approval.
Base: fork of NousResearch/hermes-agent; development branch `dev/meu-foundation`.
Target: Windows 11 native desktop, Greek-first, personal DeepSeek endpoint, optional Android bridge.

## Verified code map (source: fork at initial main)

| Concern | Existing Hermes seam | Meu strategy |
| --- | --- | --- |
| Agent lifecycle | `run_agent.py`, `agent/conversation_loop.py`, `agent/turn_*.py` | Preserve core loop and prompt-cache invariants. |
| Memory | `agent/memory_manager.py`, `agent/memory_provider.py`, `plugins/memory/` | Evaluate existing persistence, redact-before-egress and cross-session recall before adding a provider. |
| Skills | `agent/skill_utils.py`, `skills/`, `agent/curator*.py` | Introduce proposal/review/approve workflow at the skill mutation boundary; keep original skill and rollback history. |
| Desktop | `apps/desktop/` (Electron/React) | Native Windows-only acceptance tests; avoid a premature rewrite. |
| Gateway | `gateway/` | Keep Android transport behind a versioned adapter; do not expose the local desktop via an unauthenticated public port. |
| Scheduling | `cron/` | Do not activate unattended jobs until permissions and cancellation are tested. |

## Constraints

1. Never commit API keys, Telegram tokens, local chat history or private memory to this public repository.
2. Use an isolated runtime profile and distinct installation/data directory for Meu tests; do not modify the currently working Hermes installation.
3. Default to per-action consent for filesystem, shell, network and desktop control. Time-limited scopes and explicit audit entries are required before broader approvals.
4. No automatic changes to installed skill instructions or high-trust memory. Proposed changes must be inspectable and reversible.
5. Keep upstream changes reviewable. The protected integration flow is: upstream sync -> review -> branch tests -> Meu integration.
6. Do not infer native Windows GUI automation works from shell access; verify actual screen read, mouse/keyboard actions, failures and cancellation on Windows 11.
7. No trading order execution in the foundation stage; any future MT5 integration starts read-only and requires separate authorization.

## Acceptance gates

- **G0: code audit:** trace current desktop computer-use capability and permissions to actual source locations; enumerate security boundaries and regression tests.
- **G1: isolation:** a fresh Meu profile starts without reading or changing the existing Hermes profile, its secrets, or its installed skills.
- **G2: Windows smoke:** launch, chat with configured personal DeepSeek provider, read a screen, interact with a disposable test window, cancel an action, and restart.
- **G3: memory:** demonstrate cross-session recall, a correction, inspectability, versioned rollback, and no key leakage.
- **G4: skills:** unsuccessful tasks cannot silently rewrite active skills; review shows a diff; approval and rollback have tests.
- **G5: Android:** authenticated pairing, key rotation, disconnect, replay/reconnect behaviour, no unauthenticated inbound exposure.
- **G6: release:** signed/reproducible package strategy, clean Windows install and uninstall, upgrade rollback and smoke suite.

## Immediate technical observations

- Hermes describes plugin/skill extension as its preferred path and explicitly treats stable prompts/tool schemas as invariants (`AGENTS.md`).
- The existing memory manager redacts information before sending it to registered external providers (`agent/memory_manager.py`); this is a useful boundary to retain, not proof of comprehensive secret safety.
- Hermes Desktop is a real Electron UI with a Python runtime (`apps/desktop/README.md`), not merely a terminal wrapper.
- Current public fork is an upstream copy. No Meu feature is implemented or verified yet.

## Next implementation step

Inspect `tools/` and desktop Windows computer-use handling plus relevant tests, document a reproducible failure/latency baseline, and implement the smallest behaviour change with a regression test. Do not rename the entire codebase before a working isolated smoke test.


## Έλεγχος ιδιωτικότητας — 2 Νοεμβρίου 2026

Εργασία αποκλειστικά στον `dev/meu-foundation`. Βάση ελέγχου: `b62cdc9af771d97f4a9280d8f42b18510198f85e`.
Το Windows CI της βάσης ολοκληρώθηκε επιτυχώς, μαζί με τη δοκιμή installer/συντομεύσεων
([εκτέλεση 41362371240](https://github.com/rodos4312/Meu-Agent/actions/runs/41362371240)).
Τα αποτελέσματα αυτής της βάσης δεν αποτελούν επαλήθευση της νέας αλλαγής.

### Εντοπισμένοι μηχανισμοί και αλλαγές

- Ο κοινός αποστολέας `shared_metrics_sender.py` έκανε POST στο
  `https://telemetry.nousresearch.com/v1/telemetry`, με τοπική ουρά, παράθυρα συγκατάθεσης
  και επαναπροσπάθειες. Αφαιρέθηκαν η υλοποίηση HTTP, οι επαναπροσπάθειες και η αποστολή ουράς.
  Το συμβατό `send_pending()` επιστρέφει μηδενικές αποστολές ακόμη και με παλιά ουρά,
  ενεργή παλιά συγκατάθεση ή προσαρμοσμένο transport. Η απευθείας κλήση `_post()` απορρίπτεται.
- Απενεργοποιήθηκαν οι πύλες συλλογής για κύκλο ζωής agent, μοντέλα, εργαλεία, εντολές,
  engagement και ενημερώσεις. Η αποθήκευση τοπικών διαγνωστικών του agent παραμένει ξεχωριστή.
- Το Desktop δεν συλλέγει ή προωθεί μετρήσεις κουμπιών, εκκίνησης, ενημερώσεων και crashes.
  Οι συμβάσεις IPC διατηρούνται αδρανείς, ώστε εκκίνηση και ενημερώσεις να συνεχίσουν να λειτουργούν.
- Οι installers PowerShell/Bash δεν γράφουν αποδείξεις χρήσης για μελλοντική αποστολή.
- Οι ρυθμίσεις `telemetry.shared_metrics.enabled` και `send` επιβάλλονται ως `false`,
  με κενό `endpoint`. Τα παλιά τοπικά προφίλ μετατρέπονται κατά την εκκίνηση και όλοι οι
  τρόποι αποθήκευσης επιβάλλουν την ίδια πολιτική. Managed overlays και worker snapshots
  δεν μπορούν να την παρακάμψουν. Αν ένα αρχείο δεν μπορεί να μετατραπεί, η αποστολή παραμένει
  απενεργοποιημένη στον κώδικα και καταγράφεται η αποτυχία αποθήκευσης.
- Καταργήθηκαν η ερώτηση συγκατάθεσης και η δυνατότητα ενεργοποίησης από Privacy.
  Η πολιτική εξηγείται σε όλες τις υπάρχουσες γλώσσες του Desktop.
- Οι κλήσεις DeepSeek, οι ρυθμίσεις μνήμης και ο μηχανισμός έγκρισης εργαλείων δεν αντικαταστάθηκαν.
  Το προαιρετικό OpenTelemetry δεν έχει προεπιλεγμένο προορισμό στη Nous. Η χειροκίνητη
  εξαγωγή trace στο Hugging Face είναι διαφορετική λειτουργία και δεν ενεργοποιήθηκε.

### Επαληθεύσεις στο απομονωμένο Windows αντίγραφο

- **105 Python tests πέρασαν**: πολιτική συλλογής/αποστολής, παλιά ουρά, αποθήκευση και
  επανεκκίνηση, named-profile RPC, Windows installer, DeepSeek, τοπική συμβατότητα SQLite.
- **26 UI tests πέρασαν** και **15 Electron tests πέρασαν**. Ένα υπάρχον Electron test
  άλλης πλατφόρμας παραλείφθηκε στο Windows περιβάλλον.
- **3 tests ορίου παράλληλων agent πέρασαν**. Πέρασε ο έλεγχος τύπων Desktop/Electron.
- Οι **20 νέες δοκιμές ιδιωτικότητας απέτυχαν στην αρχική έκδοση**, και πέρασαν μετά την αλλαγή.
  Η δοκιμή DeepSeek χρησιμοποιεί τον πραγματικό SDK/transport με προσομοιωμένη HTTP απάντηση:
  αίτημα εργαλείου, επιστροφή αποτελέσματος και τελική απάντηση. Δεν έγινε κλήση σε πραγματικό
  λογαριασμό DeepSeek ούτε χρήση προσωπικού API key.
- Πέρασαν οι έλεγχοι ποιότητας και συμβάσεων ανάγνωσης/εγγραφής config.
  Το workflow `meu-windows-validation.yml` περιλαμβάνει πλέον ξεχωριστό Windows job
  ιδιωτικότητας/DeepSeek και τις νέες δοκιμές Desktop πριν τη συσκευασία.

Η πλήρης upstream σουίτα δεν εκτελέστηκε. Οι παλιές δοκιμές που απαιτούν ενεργό upload
δεν περιγράφουν την πολιτική του Meu και χρειάζονται ξεχωριστή προσαρμογή όταν επεκταθεί
η συνολική κάλυψη του fork. Τα ιστορικά τοπικά αρχεία τηλεμετρίας δεν διαγράφηκαν μαζικά·
ο νέος κώδικας δεν τα αποστέλλει. Η εγκατεστημένη εφαρμογή του χρήστη δεν ενημερώθηκε
από αυτή την εργασία. Η μετονομασία, η τελική έκδοση installer, η γενική σταθερότητα,
η ασφάλεια και η μνήμη παραμένουν ξεχωριστά στάδια με δικές τους δοκιμές αποδοχής.
