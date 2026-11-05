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
([εκτέλεση 41362371240](https://github.com/rodos4312/Meu-Agent-Legacy/actions/runs/41362371240)).
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

## Επόμενα στάδια — 2 Νοεμβρίου 2026

Βάση: `a6b43264df4594843bc8ab43370882faac5bf754`, με επιτυχημένο
[Windows CI 41364602590](https://github.com/rodos4312/Meu-Agent-Legacy/actions/runs/41364602590).
Η παρούσα ενότητα καταγράφει νεότερες αποφάσεις από τα αρχικά gates παραπάνω.
Η οδηγία του ιδιοκτήτη είναι να διατηρηθούν οι υπάρχουσες ρυθμίσεις έγκρισης για
μνήμη, skills και χρήση οθόνης: δεν προστέθηκαν επαναλαμβανόμενες ερωτήσεις ή νέες
προεπιλεγμένες εγκρίσεις. Το G4 δεν αποτελεί εντολή αλλαγής αυτών των ρυθμίσεων.

### Μετονομασία και πρακτική χρήση

- Τα εμφανιζόμενα ονόματα στο Desktop και στις υπάρχουσες μεταφράσεις χρησιμοποιούν Meu.
  Τα συμβατά εσωτερικά ονόματα, τα πρωτόκολλα και οι πραγματικές αναφορές σε εξωτερικούς
  παρόχους παραμένουν. Οι άδειες και η αναφορά στην upstream προέλευση διατηρούνται.
- Διορθώθηκε ο πραγματικός μηχανισμός εγγραφής Windows resources: το εκτελέσιμο
  αποκτά όνομα, περιγραφή, εταιρεία και εικονίδιο Meu. Έκδοση ανάπτυξης `0.1.0-dev.1`.
- Η συσκευασία περιλαμβάνει την άδεια MIT της βάσης, και η απεγκατάσταση κρατά τα
  δεδομένα για πιθανή επανεγκατάσταση. Δεν δημιουργήθηκε επίσημη υπογεγραμμένη έκδοση.

### Μνήμη με δυνατότητα διόρθωσης

- Κάθε πραγματική αλλαγή κρατά την προηγούμενη έκδοση τοπικά στο ενεργό προφίλ,
  μέχρι 50 εκδόσεις ανά αρχείο μνήμης/χρήστη. Δεν προστέθηκε νέο model tool ή upload.
- Από την υπάρχουσα εντολή `/memory`: `show` εμφανίζει τη μνήμη, `history` τις εκδόσεις,
  `diff <id>` τις διαφορές και `restore <id>` επαναφέρει την επιλεγμένη έκδοση.
  Το σύντομο id της λίστας αρκεί όταν είναι μοναδικό. Η επαναφορά διατηρεί αντίγραφο
  της τρέχουσας έκδοσης, άρα μπορεί και αυτή να αναιρεθεί.
- Οι αλλαγές διαβάζονται από νέες συνομιλίες. Το σταθερό system prompt της τρέχουσας
  συνομιλίας παραμένει ανέπαφο. Αποτυχία εγγραφής δεν αφήνει ψευδώς ενημερωμένη τη
  ζωντανή μνήμη. Διατηρούνται οι υφιστάμενοι έλεγχοι περιεχομένου και τα όρια μεγέθους.
- Η ταξινόμηση εντολών gateway ξεχωρίζει την ανάγνωση από την επαναφορά, εφαρμόζοντας
  τα υπάρχοντα δικαιώματα. Οι αυτόματες εγγραφές και οι προτιμήσεις έγκρισης δεν άλλαξαν.

### Windows και αποδεικτικά ελέγχων

- Τοπικά πέρασαν **469 Python tests**, με **3 παραλείψεις αποκλειστικά POSIX**,
  για τηλεμετρία/DeepSeek, μνήμη, διόρθωση, πραγματική επανεκκίνηση Python, αποτυχία
  δίσκου, ταυτόχρονες εγγραφές, redaction, secret scopes και διατήρηση πολιτικής εγκρίσεων.
- Πέρασαν **132 UI tests** και **41 Electron/native tests**· ένα υπάρχον test άλλης
  πλατφόρμας παραλείφθηκε. Οι 9 νέες δοκιμές μνήμης/gateway και οι 2 native δοκιμές
  αποτυγχάνουν στη βάση χωρίς τις διορθώσεις τους.
- Πέρασε η τοπική παραγωγή και συσκευασία Windows. Η πραγματική συσκευασμένη εφαρμογή
  άνοιξε δύο φορές με απομονωμένο προφίλ και προσομοιωμένο backend: αρχική οθόνη
  «Set up Meu», ενεργό «Install Meu locally», χωρίς ερώτηση usage stats.
- Η πρώτη δοκιμή αποκάλυψε ότι το Meu παρέκαμπτε την υπάρχουσα παράκαμψη διαδρομής
  δεδομένων Desktop. Διορθώθηκε πριν επαναληφθεί επιτυχώς η δοκιμή και προστέθηκε
  regression test. Η πρώτη αποτυχημένη εκκίνηση είχε διαβάσει τον συνηθισμένο φάκελο
  ρυθμίσεων Desktop· δεν εκτέλεσε εργασία agent. Δεν εγκαταστάθηκε νέα έκδοση στον χρήστη.
- Το Windows CI δοκιμάζει πλέον πραγματική εκκίνηση/restart του εγκατεστημένου renderer,
  συντομεύσεις, όνομα εκτελέσιμου, άδεια, repair, uninstall και reinstall με διατήρηση
  δοκιμαστικού προφίλ. Κρατά screenshots και στοιχεία εκκίνησης ως artifacts.
  Ο έλεγχος installer επιτρέπεται μόνο στον αναλώσιμο runner του GitHub.

Η επιτυχία του νέου CI πρέπει να ελεγχθεί στο ακριβές commit μετά τη δημοσίευση.
Δεν εκτελέστηκε όλη η upstream σουίτα, ζωντανή χρεώσιμη κλήση DeepSeek, δοκιμή
χειρισμού προσωπικών εφαρμογών ή Android pairing. Η υπογραφή διανομής και η δοκιμή
στην πραγματική καθημερινή χρήση παραμένουν ανοιχτά κριτήρια αποδοχής.

## Οθόνη Models και Auto — έκδοση ανάπτυξης 0.1.0-dev.2

Βάση: `74493f1d7b5e096ea723a25a890e52d1b2721a11`. Αιτία της κρυμμένης εισαγωγής
κλειδιού: το Desktop αντιμετώπιζε μια λίστα αποθηκευμένων μοντέλων ως επαρκή ένδειξη
σύνδεσης, ακόμη και με `authenticated: false`. Επιπλέον, ο κατάλογος παρέλειπε τα
`auth_type`/`key_env` στους ήδη συνδεδεμένους παρόχους.

- Το Models εμφανίζει ξεχωριστό πεδίο API key, ακόμη και μετά τη σύνδεση. Το πεδίο
  είναι κρυφό και κενό: δεν αποκαλύπτει το αποθηκευμένο κλειδί. Η αντικατάσταση
  χρησιμοποιεί τον υπάρχοντα writer και διατηρεί την επιλεγμένη διαδρομή μοντέλου.
  Η ένδειξη «αποθηκεύτηκε» σημαίνει αποθήκευση, όχι απόδειξη εγκυρότητας του key.
- Στο DeepSeek προστέθηκε προαιρετικό **Auto · Flash / Pro**, με προεπιλογή off.
  Αποθηκεύεται στο ενεργό προφίλ μέσω του κανονικού config API και εφαρμόζεται σε
  νέες συνομιλίες. Ούτε η μνήμη ούτε τα skills απέκτησαν νέες απαιτήσεις έγκρισης.
- Η πρώτη υλοποίηση είναι τοπική ευρετική επιλογή: μικρές απλές εργασίες →
  `deepseek-flash`, μεγαλύτερα αιτήματα/κώδικας/ανάλυση → `deepseek-v4-pro`.
  Δεν είναι αλάνθαστη αξιολόγηση δυσκολίας και δεν πραγματοποιεί πρόσθετη κλήση
  σε μοντέλο για ταξινόμηση. Οι επίσημες τρέχουσες δυνατότητες ελέγχθηκαν στην
  [τεκμηρίωση DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/).
- Η διαδρομή μένει σταθερή κατά την εκτέλεση μιας εργασίας και των εργαλείων της.
  Ένα «συνέχισε» κληρονομεί την προηγούμενη ουσιαστική εργασία. Εικόνες στο replay
  απαιτούν Flash, επειδή το τρέχον Pro είναι text-only. Δεν αλλάζει το ιστορικό,
  το system prompt, οι διαθέσιμες λειτουργίες ή οι ανεξάρτητες auxiliary αναθέσεις.
- Η τοπική λογιστική και τα API request hooks αναφέρουν το συγκεκριμένο μοντέλο
  του αιτήματος. Τα routing logs περιέχουν μόνο πάροχο και μοντέλο.
- Ο backend δηλώνει ρητά αν υποστηρίζει Auto. Σε παλιότερο backend το νέο Desktop
  εξακολουθεί να επιτρέπει εισαγωγή κλειδιού DeepSeek, αλλά δεν προσφέρει ανενεργό
  διακόπτη Auto. Εμφανίζει την ανάγκη ενημέρωσης και έλεγχο ξανά μετά την ενημέρωση.
  Αυτός ο έλεγχος διαβάζει τον κατάλογο· δεν αλλάζει κανάλι ή κλάδο backend.

Οι νέες δοκιμές αναπαρήγαγαν τα προβλήματα στη βάση: **15 Python και 5 UI tests
απέτυχαν χωρίς τις διορθώσεις**. Η προσομοιωμένη διαδρομή DeepSeek χρησιμοποιεί
πραγματικό agent/SDK με tool round-trip, frozen routing config, πραγματική
αποθήκευση/επανεκκίνηση και έλεγχο τιμολόγησης στο επιλεγμένο μοντέλο.
Δεν χρησιμοποιήθηκαν προσωπικά API keys ή ζωντανές χρεώσιμες κλήσεις.

Στο απομονωμένο Windows περιβάλλον πέρασαν **150 σχετικά Python tests** και
**140 UI/i18n tests**, μαζί με τον έλεγχο του παραγόμενου συμβολαίου επικοινωνίας.
Το Windows CI διατηρεί επιπλέον ολόκληρη την προηγούμενη σουίτα ιδιωτικότητας,
μνήμης και installer και ελέγχει το ακριβές νέο commit πριν διατεθεί ο installer.
