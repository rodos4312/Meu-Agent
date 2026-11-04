# Meu Agent

<img src="https://raw.githubusercontent.com/rodos4312/Meu-Agent/bd5872478b7b683e7b809e70239acd26f0e9fb1e/apps/desktop/public/meu-icon.png" alt="Λογότυπο Meu" width="72">

Ο **Meu** είναι προσωπικός βοηθός για Windows. Δουλεύει με τα αρχεία και τα έργα σου, θυμάται προηγούμενες συνομιλίες και μπορεί να μοιράζει σύνθετες δουλειές σε βοηθούς.

## Λήψη για Windows x64

**[Λήψη Meu 0.1.0-dev.18 για Windows x64](https://github.com/rodos4312/Meu-Agent/releases/download/meu-v0.1.0-dev.18/Meu-0.1.0-dev.18-win-x64.exe)** · Δοκιμαστική έκδοση

Στις [εκδόσεις του Meu](https://github.com/rodos4312/Meu-Agent/releases) θα βρεις τις σημειώσεις και τα διαθέσιμα αρχεία εγκατάστασης.

Μετά την εγκατάσταση, βάλε το κλειδί DeepSeek από **Settings → Model → Main model**. Τις επόμενες εκδόσεις μπορείς να τις ελέγχεις από **Settings → About → Version & updates**.

## Τι προσφέρει ο Meu

- **DeepSeek Auto · Flash / Pro.** Ο Meu επιλέγει ανάμεσα στα δύο μοντέλα ανάλογα με την εργασία. Μπορείς επίσης να επιλέξεις μοντέλο από τη συνομιλία.
- **Meu Coordinator.** Οργανώνει ένα έργο σε αναθέσεις, αποθηκεύει την πρόοδο και δίνει σε βοηθούς συγκεκριμένες εργασίες. Μπορεί να αναθέσει ανεξάρτητο έλεγχο και διόρθωση. Ενεργοποιείται από **Settings → Model → Subagents** για νέα συνομιλία.
- **Τοπικά δεδομένα και επιλογή παρόχου.** Η τοπική εγκατάσταση διατηρεί συνομιλίες, μνήμη και skills στο PC. Οι κλήσεις μοντέλου και αναζήτησης πηγαίνουν στους αντίστοιχους παρόχους. Η σύνδεση στο Nous Portal και η αποστολή στατιστικών χρήσης στη Nous έχουν αφαιρεθεί από τον Meu.

## Κώδικας και προέλευση

Η ανάπτυξη γίνεται στον [`dev/meu-foundation`](https://github.com/rodos4312/Meu-Agent/tree/dev/meu-foundation).

Ο Meu βασίζεται στο [Hermes Agent της Nous Research](https://github.com/NousResearch/hermes-agent). Ο αρχικός κώδικας διανέμεται με την [άδεια MIT](LICENSE).
