# Watcher slot TestFlight WhatsApp

Controlla ogni pochi minuti la pagina pubblica TestFlight di WhatsApp e ti manda
una notifica push sul telefono quando smette di dire *"This beta isn't accepting
any new testers right now"*.

Gira su GitHub Actions: niente server, niente NAS, niente Mac acceso.

## Come capisce se e' aperto

Apple serve due pagine diverse allo stesso URL:

| Stato | Cosa c'e' nell'HTML |
|---|---|
| chiuso | `<title>TestFlight - Apple</title>` + "This beta isn't accepting any new testers right now." |
| **aperto** | `<title>Join the WhatsApp Messenger beta - TestFlight - Apple</title>` |
| codice morto | HTTP 404 |

Il controllo si basa sul titolo `Join the ... beta`, verificato su beta realmente
aperti. Se la pagina non corrisponde a nessuno stato noto (Apple rifa' l'HTML),
lo stato diventa `UNKNOWN` e **ti avvisa lo stesso**: meglio un falso allarme
che perdere lo slot in silenzio.

## Setup (10 minuti, una volta sola)

### 1. Le notifiche sul telefono

Installa **ntfy** da App Store (gratis, niente registrazione). Aprila, tocca +,
e iscriviti a un topic con un nome lungo e casuale, per esempio:

    wa-tf-sxf3eo2m77fzy14k

> I topic su ntfy.sh sono pubblici: chi indovina il nome legge le tue notifiche.
> Per questo serve un nome impossibile da indovinare, e va messo nei **Secrets**.

In Impostazioni iOS, dai a ntfy il permesso di notificare e consenti l'app
anche in Full Immersion, altrimenti di notte non suona.

### 2. Il repository

Crea un repo **pubblico** su GitHub e caricaci questi file.

> Pubblico non e' un dettaglio: sui repo privati i minuti di Actions sono 2000
> al mese, e un controllo ogni 5 minuti ne consuma circa 8600. Sul pubblico sono
> illimitati. Nel repo non finisce niente di sensibile: il topic sta nei Secrets.

### 3. Le impostazioni del repo

In **Settings → Secrets and variables → Actions**:

Tab **Variables** → New repository variable:

| Nome | Valore |
|---|---|
| `TF_CODES` | `krUFQpyJ,YcmGWyxV` |
| `HEARTBEAT_DAYS` | `7` |

Tab **Secrets** → New repository secret:

| Nome | Valore |
|---|---|
| `NTFY_TOPIC` | il topic scelto al punto 1 |

### 4. Accendi

Vai su **Actions**, abilita i workflow, apri "Watch TestFlight" e premi
**Run workflow** per provarlo subito. Nel log devi vedere una riga tipo:

    [krUFQpyJ] - -> CLOSED: This beta isn't accepting any new testers right now.

Da li' in poi va da solo.

## Cosa aspettarti davvero

**Il cron ogni 5 minuti non e' ogni 5 minuti.** GitHub mette i job schedulati in
coda a bassa priorita': nella pratica partono con 10-25 minuti di ritardo, e
sotto carico qualche giro viene proprio saltato. Per "ogni 10/20 minuti" va
benissimo; per il tempo reale no. Se ti serve davvero il minuto, vedi
`cloudflare-worker.js`.

**Buona notizia:** quando WhatsApp riapre il programma, i posti non spariscono in
trenta secondi. Di solito la finestra dura da qualche decina di minuti a qualche
ora. Un controllo ogni 10-15 minuti la prende.

**GitHub spegne i cron dopo 60 giorni** senza attivita' nel repo. Ti arriva una
mail prima: basta un commit qualsiasi per riazzerare il contatore.

**Apple potrebbe bloccare gli IP dei runner.** Se succede, dopo 6 controlli
falliti di fila ricevi una notifica "Watcher in errore" invece di restare
all'oscuro. Con `HEARTBEAT_DAYS=7` ricevi anche un "watcher vivo" settimanale:
se smette di arrivare, qualcosa si e' rotto.

## Aggiungere nuovi codici invito

WhatsApp cambia link nel tempo. Il link corrente lo pubblica WABetaInfo su
<https://wabetainfo.com/testflight/>. Quando ne esce uno nuovo, aggiungilo alla
variabile `TF_CODES` separato da virgola: il watcher li controlla tutti.

## Provarlo sul tuo Mac

    TF_CODES="krUFQpyJ,YcmGWyxV" python3 check.py --dry-run

Con `--dry-run` non salva lo stato. Per provare anche la notifica:

    TF_CODES="krUFQpyJ" NTFY_TOPIC="il-tuo-topic" python3 check.py --dry-run

## File

- `check.py` — il controllo. Solo libreria standard, nessuna dipendenza.
- `.github/workflows/watch.yml` — lo scheduler.
- `state.json` — stato corrente, committato solo quando cambia qualcosa.
- `cloudflare-worker.js` — variante opzionale, controllo ogni minuto.
