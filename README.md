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
| `TF_CODES` | `YcmGWyxV:WhatsApp iOS,krUFQpyJ` |
| `HEARTBEAT_HOUR` | `9` |
| `TELEGRAM_CHAT_ID` | il tuo ID numerico (vedi sotto) |

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
all'oscuro.

**Il battito quotidiano.** Con `HEARTBEAT_HOUR=9` ricevi ogni mattina un
"Watcher vivo" con lo stato dei codici. Serve a una cosa sola, ma importante:
un watcher che muore in silenzio e' indistinguibile da un watcher che non ha
niente da dire. Se una mattina il messaggio non arriva, sai che devi guardare.

L'ora e' ancorata al calendario locale (`HEARTBEAT_TZ`, default `Europe/Rome`):
si batte al primo controllo dopo le 9:00 di ogni giorno, una volta sola. Non
deriva col passare dei giorni e non ha casi particolari ai cambi dell'ora.
Siccome il cron di GitHub ritarda, in pratica arriva fra le 9:00 e le 9:25.
Per spegnerlo, imposta `HEARTBEAT_HOUR` a stringa vuota.

## Cloudflare: il secondo watcher

> **Stato: funziona tutto, cron compreso.**
> Verificato il 17/09/2026 nella dashboard, sotto
> **Worker → Observability → Events** con la finestra su un'ora: 12 esecuzioni,
> 0 errori, barre equidistanti, e ogni riga ha come messaggio l'espressione
> `*/5 * * * *`. E' cosi' che Cloudflare etichetta un'invocazione schedulata:
> quelle righe **sono** i tick del cron. In pari data: 186 richieste dall'inizio
> della giornata UTC, contro le ~187 che un tick ogni 5 minuti produce.
>
> **La diagnosi del 16/09 ("il cron non esegue") era sbagliata**, e vale la pena
> ricordare perche', perche' e' l'errore che si rifa' volentieri: era fondata sul
> contatore delle invocazioni e sui log realtime, guardati per pochi minuti.
> Il contatore e' aggregato e arriva in ritardo, i log realtime mostrano solo
> cio' che passa mentre li guardi, e il worker in stato CLOSED -> CLOSED non
> stampa niente. Tre strumenti che, per motivi diversi, non potevano mostrare
> quello che si cercava.
>
> Il posto giusto e' **Observability → Events**. Se un domani ti serve
> ricontrollare, guarda li' e basta.
>
> Nota: il trigger attivo e' `*/5 * * * *`, cinque minuti, non un minuto.

Far girare **anche** il Worker, in parallelo a GitHub Actions e sullo stesso
topic ntfy, da':

- controllo **puntuale**: il cron di Cloudflare parte quando dice, mentre
  GitHub arriva con 13-21 minuti di ritardo
- due cloud indipendenti: se GitHub si ferma, Cloudflare continua, e viceversa
- nessun limite di 60 giorni di inattivita'
- costo zero (288 richieste al giorno a `*/5`, sulle 100.000 gratuite)

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
| Variable | `TF_CODES` | `YcmGWyxV:WhatsApp iOS,krUFQpyJ` |
| Secret | `NTFY_TOPIC` | il tuo topic ntfy |

> `NTFY_TOPIC` va aggiunto come **Secret**, non come Variable: le Variable si
> leggono in chiaro dalla dashboard, i Secret no.

### 4. Accendi il cron

**Settings → Triggers → Cron Triggers → Add**, espressione:

    */5 * * * *

Cinque minuti sono piu' che sufficienti: la finestra in cui WhatsApp riapre
dura da decine di minuti a qualche ora. Se vuoi il minuto metti `* * * * *`;
costa 1.440 invocazioni al giorno sulle 100.000 gratuite, quindi si puo' fare.

### 5. Prova subito

Apri l'URL del worker (`https://testflight-watch.<tuo-sottodominio>.workers.dev`)
in un browser: risponde con lo stato in JSON. Deve uscire una cosa cosi':

    [{"code":"krUFQpyJ","prev":"CLOSED","state":"CLOSED","detail":"This beta isn't accepting..."}]

Se vedi `"state":"CLOSED"` funziona. Se vedi un errore su `STATE`, il binding
KV del punto 3 non e' stato salvato.

Per verificare che sia il **cron** a muoverlo, e non la tua visita, vai in
**Observability → Events** e metti la finestra su un'ora: devi vedere una riga
per tick, con l'espressione cron come messaggio.

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

**Telegram (piu' solido).** Oltre a risolvere la quota ti da' un canale
indipendente da ntfy: se uno dei due ha un disservizio, l'altro passa lo stesso.

1. Crea un bot con **@BotFather** (`/newbot`) e copia il token.
2. Aggiungilo come **secret** `TELEGRAM_BOT_TOKEN`.
3. Scrivi a **@userinfobot**: ti risponde col tuo ID numerico. Mettilo in
   `TELEGRAM_CHAT_ID`. Sul repo GitHub va bene indifferentemente come Secret o
   come Variable: il workflow guarda in entrambi i posti. Non e' un segreto,
   quindi Variable e' piu' comodo (si rilegge, un Secret no).
4. **Apri il tuo bot e mandagli `/start`.**

Il punto 4 non e' opzionale e non e' un dettaglio: Telegram vieta a un bot di
scrivere per primo a chi non gli ha mai parlato. Finche' non lo fai, l'API
risponde `400 {"description":"Bad Request: chat not found"}` e la notifica non
parte, anche se token e chat_id sono perfetti. E' l'errore piu' comune di
questa configurazione.

Il codice prova tutti i canali configurati in parallelo e considera la notifica
consegnata se **almeno uno** arriva. Se non ne arriva nessuno, lo stato non
viene salvato e al giro dopo riprova.

### Come capisci quale dei due e' morto

Arrivano sullo stesso bot Telegram, quindi ogni messaggio si apre con
l'etichetta di chi l'ha scritto: **Git** dal watcher GitHub, **CldF** dal
Worker Cloudflare. Ogni mattina alle 9 ne arrivano due:

    ✅ Git · Watcher vivo
    ✅ CldF · Watcher Cloudflare vivo

Due messaggi = tutto a posto. Uno solo = quell'altro e' morto, e l'etichetta ti
dice gia' dove guardare. Nessuno dei due = sono morti entrambi, oppure e'
Telegram ad avere problemi.

L'emoji risponde a una domanda sola, prima ancora di leggere: il watcher sta
facendo il suo lavoro?

| | |
|---|---|
| ✅ | tutto regolare, e' il battito quotidiano |
| ❌ | non sta funzionando: controlli falliti di fila, o codice invito sparito |
| 🚨 | lo slot e' aperto, vai |
| 🔒 | lo slot si e' richiuso |

Le prime due riguardano la salute del watcher, le altre due l'evento che stavi
aspettando: sono cose diverse e per questo hanno icone diverse.

## Aggiungere nuovi codici invito

WhatsApp cambia link nel tempo. Il link corrente lo pubblica WABetaInfo sulla
pagina dedicata <https://wabetainfo.com/wa-testflight/> — non sull'indice
generale, dove la scheda WhatsApp rimanda qui invece di linkare TestFlight.
Al 17/09/2026 il codice pubblicato e' `YcmGWyxV`.

I codici si separano con la virgola, e ognuno puo' avere un nome dopo i due
punti:

    TF_CODES = "YcmGWyxV:WhatsApp iOS,krUFQpyJ"

Il nome e' quello che leggi nella notifica. Senza nome compare il codice, che
alle 9 del mattino non dice niente a nessuno.

> **Una beta chiusa non rivela di che app sia.** Verificato scaricando due
> pagine di codici diversi: a parte il codice nell'URL sono identiche byte per
> byte, 39045 byte, e l'unico `app-id` presente e' 899247664, che e' TestFlight
> stesso. Il nome dell'app compare solo quando il programma apre, nel titolo
> `Join the <App> beta`. Quindi di un codice che non trovi documentato da
> nessuna parte non puoi sapere niente finche' non apre.

## Provarlo sul tuo Mac

    TF_CODES="krUFQpyJ,YcmGWyxV" python3 check.py --dry-run

Con `--dry-run` non salva lo stato. Per provare anche la notifica:

    TF_CODES="krUFQpyJ" NTFY_TOPIC="il-tuo-topic" python3 check.py --dry-run

## File

- `check.py` — il controllo. Solo libreria standard, nessuna dipendenza.
- `.github/workflows/watch.yml` — lo scheduler.
- `state.json` — stato corrente, committato solo quando cambia qualcosa.
- `cloudflare-worker.js` — variante opzionale, controllo ogni minuto.
