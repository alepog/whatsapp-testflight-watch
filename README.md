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

## Cloudflare: il secondo watcher (opzionale ma consigliato)

Far girare **anche** il Worker, in parallelo a GitHub Actions e sullo stesso
topic ntfy, da':

- controllo ogni **minuto** invece di 5-25, perche' il cron di Cloudflare e' puntuale
- due cloud indipendenti: se GitHub si ferma, Cloudflare continua, e viceversa
- nessun limite di 60 giorni di inattivita'
- costo zero (~1.440 richieste al giorno sulle 100.000 gratuite)

Quando il beta apre ricevi due notifiche invece di una. Per questo caso e' un
vantaggio: una doppia costa due secondi di fastidio, una mancata costa un anno.

Si fa tutto dal browser, **senza installare Node ne' wrangler**.

### 1. Crea lo spazio dove ricorda lo stato

Dashboard Cloudflare → **Storage & Databases → KV** → *Create a namespace*.
Chiamalo `testflight-state`.

### 2. Crea il Worker

**Compute (Workers) → Create → Worker**. Dagli un nome, per esempio
`testflight-watch`, e premi *Deploy* accettando il codice di esempio.
Poi **Edit code**: cancella tutto, incolla il contenuto di
`cloudflare-worker.js` e premi *Deploy* di nuovo.

### 3. Collega le impostazioni

Nel Worker, **Settings → Bindings → Add**:

| Tipo | Nome | Valore |
|---|---|---|
| KV namespace | `STATE` | il namespace `testflight-state` |
| Variable | `TF_CODES` | `krUFQpyJ,YcmGWyxV` |
| Secret | `NTFY_TOPIC` | il tuo topic ntfy |

> `NTFY_TOPIC` va aggiunto come **Secret**, non come Variable: le Variable si
> leggono in chiaro dalla dashboard, i Secret no.

### 4. Accendi il cron

**Settings → Triggers → Cron Triggers → Add**, espressione:

    * * * * *

### 5. Prova subito

Apri l'URL del worker (`https://testflight-watch.<tuo-sottodominio>.workers.dev`)
in un browser: risponde con lo stato in JSON. Deve uscire una cosa cosi':

    [{"code":"krUFQpyJ","prev":null,"state":"CLOSED","detail":"This beta isn't accepting..."}]

Se vedi `"state":"CLOSED"` funziona. Se vedi un errore su `STATE`, il binding
KV del punto 3 non e' stato salvato.

### Importante: la quota di ntfy.sh e' per indirizzo IP

ntfy.sh gratuito conta la quota giornaliera di messaggi **per IP di chi
pubblica**, non per topic. I Worker Cloudflare escono da IP condivisi con
migliaia di altri utenti, e quella quota di solito e' gia' esaurita: il Worker
riceve `429 {"code":42908}` e la notifica non parte. Verificato dal vivo.

Lo stesso rischio, piu' raro, vale per i runner di GitHub Actions.

Due modi per togliersi il problema, gia' supportati dal codice:

**Token ntfy (veloce).** Crea un account gratuito su ntfy.sh, genera un access
token, e aggiungilo come secret `NTFY_TOKEN` — sul Worker e, volendo, anche nei
Secrets del repo GitHub. Con il token la quota e' del tuo account invece che
dell'IP condiviso.

**Telegram (piu' solido).** Crea un bot con @BotFather, prendi il token, scrivi
un messaggio al bot e leggi il tuo `chat_id` da
`https://api.telegram.org/bot<TOKEN>/getUpdates`. Aggiungi `TELEGRAM_BOT_TOKEN`
e `TELEGRAM_CHAT_ID` come secret. Oltre a risolvere la quota, ti da' un secondo
canale indipendente: se ntfy ha un disservizio, Telegram passa lo stesso.

Il codice prova tutti i canali configurati in parallelo e considera la notifica
consegnata se **almeno uno** arriva. Se non ne arriva nessuno, lo stato non
viene salvato e al giro dopo riprova.

### Come capisci quale dei due e' morto

I due watcher mandano heartbeat con titoli diversi, una volta a settimana:
"Watcher vivo" da GitHub, "Watcher Cloudflare vivo" da Cloudflare. Due battiti =
tutto a posto. Uno solo = quell'altro e' morto, e sai dove guardare. Nessuno dei
due = sono morti entrambi.

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
