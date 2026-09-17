#!/usr/bin/env python3
"""Watch TestFlight public-link pages and push a notification when one opens up.

Stdlib only. Exit code is always 0 unless something is badly broken, so a
transient network blip never turns the whole run red.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Phrases Apple serves when a public link exists but you cannot join.
CLOSED_MARKERS = (
    "isn't accepting any new testers",
    "this beta is full",
    "this beta has expired",
    "this beta isn't available",
    "this beta build has expired",
)

STATE_FILE = os.environ.get("STATE_FILE") or "state.json"

# Consecutive failed checks before we warn that the watcher itself is broken.
ERROR_STREAK_ALERT = int(os.environ.get("ERROR_STREAK_ALERT") or 6)


def fetch(code, attempts=3):
    """Return (http_status, body). http_status is None on network failure."""
    url = f"https://testflight.apple.com/join/{code}"
    last_err = None
    for i in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - any transport problem is retryable
            last_err = e
            if i < attempts - 1:
                time.sleep(3 * (i + 1))
    return None, f"network error: {last_err}"


def text_of(pattern, body):
    m = re.search(pattern, body, re.S | re.I)
    if not m:
        return ""
    inner = re.sub(r"(?s)<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", html.unescape(inner)).strip()


def classify(status, body):
    """Return (state, human_readable_detail)."""
    if status is None:
        return "ERROR", body
    if status == 404:
        return "GONE", "404 - questo codice invito non esiste piu'"
    if status != 200:
        return "ERROR", f"HTTP {status}"

    title = text_of(r"<title[^>]*>(.*?)</title>", body)
    beta_status = text_of(r'<div class="beta-status">(.*?)</div>', body)
    detail = beta_status or title or "(nessun testo di stato trovato)"
    haystack = f"{title} {beta_status}".lower()

    # Positive signal first: Apple titles an open page "Join the <App> beta".
    if re.search(r"\bjoin the .+ beta\b", title, re.I):
        return "OPEN", detail
    for marker in CLOSED_MARKERS:
        if marker in haystack:
            return "CLOSED", detail
    # Page rendered but matches nothing we know: Apple changed the markup, or
    # it is an open state we have not seen. Treat as noteworthy, never silent.
    return "UNKNOWN", detail


# Quale dei due watcher ha scritto. I messaggi arrivano sullo stesso bot, e
# senza etichetta non distingueresti un GitHub morto da un Cloudflare morto.
FONTE = os.environ.get("WATCHER_LABEL", "").strip() or "Git"

# Il repo resta in ASCII puro anche nelle stringhe: il sorgente del worker
# passa per gli appunti prima di arrivare su Cloudflare, e un carattere
# letterale li' si rompe (un "\u00b7" e' diventato "\u00ac\u2211" in produzione).
PUNTO = "\u00b7"

# Un codice invito non dice niente a chi legge la notifica alle 9 del mattino.
STATI = {
    "OPEN": "APERTO",
    "CLOSED": "chiuso",
    "GONE": "link morto (404)",
    "ERROR": "errore di controllo",
    "UNKNOWN": "stato non riconosciuto",
}


def leggi_codici(raw):
    """"YcmGWyxV:WhatsApp iOS, krUFQpyJ" -> [(codice, nome), ...].

    Il nome dopo i due punti e' facoltativo; senza, il nome e' il codice.
    """
    coppie = []
    for pezzo in raw.split(","):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        codice, _, nome = pezzo.partition(":")
        codice = codice.strip()
        if codice:
            coppie.append((codice, nome.strip() or codice))
    return coppie

# Le stesse tag che ntfy usa per le sue icone, riusate come emoji su Telegram:
# un solo posto da toccare quando si aggiunge un tipo di avviso.
#
# La spunta e la croce rispondono a una domanda sola, a colpo d'occhio:
# il watcher sta facendo il suo lavoro? Il resto e' l'evento, non lo stato
# di salute, e ha un'icona sua.
TG_EMOJI = {
    "heartbeat": "\u2705",        # vivo e vegeto
    "warning": "\u274c",          # non sta funzionando: guardaci
    "ghost": "\u274c",            # codice invito morto: serve sostituirlo
    "rotating_light": "\U0001f6a8",  # lo slot e' aperto
    "lock": "\U0001f512",            # lo slot si e' richiuso
    "eyes": "\U0001f440",
}


def telegram_body(title, message, url, tags, links=None, righe_stato=None):
    """Messaggio Telegram in HTML.

    HTML e non Markdown: il testo di stato lo scrive Apple, e un singolo
    underscore o asterisco spaiato fa fallire il parsing dell'intero messaggio,
    con Telegram che risponde 400 e la notifica che non parte. In HTML bastano
    tre caratteri da escapare e il problema non esiste.
    """
    emoji = TG_EMOJI.get(tags, TG_EMOJI["eyes"])
    testa, _, coda = message.partition("\n")
    righe = [f"{emoji} <b>{html.escape(FONTE)} {PUNTO} {html.escape(title)}</b>", ""]
    if testa:
        righe.append(html.escape(testa))
    # La seconda riga e' sempre il testo grezzo di Apple: in corsivo si legge
    # come citazione e non si confonde con la frase scritta da noi.
    if coda.strip():
        righe.append(f"<i>{html.escape(coda.strip())}</i>")
    # Il battito elenca i beta, uno per riga, col nome cliccabile: un link
    # generico a testflight.apple.com apre l'app sulla schermata iniziale.
    if righe_stato:
        for nome, u, stato in righe_stato:
            righe.append(
                f'<a href="{html.escape(u, quote=True)}">{html.escape(nome)}</a>'
                f" \u2014 {html.escape(stato)}"
            )
    else:
        voci = links or [("Apri in TestFlight", url)]
        righe += ["", f" {PUNTO} ".join(
            f'<a href="{html.escape(u, quote=True)}">{html.escape(t)}</a>' for t, u in voci
        )]
    return "\n".join(righe)


def notify(title, message, url, priority="default", tags="eyes", links=None, righe_stato=None):
    """Return True se almeno un canale ha ricevuto, o se non ne e' configurato."""
    sent = []
    failed = []

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        server = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
        # Su iOS testflight.apple.com e' un universal link: l'https apre
        # direttamente l'app TestFlight, e al massimo ripiega su Safari.
        # itms-beta:// e' la scorciatoia esplicita, come secondo tentativo.
        deep = url.replace("https://", "itms-beta://", 1)
        try:
            headers = {
                "Title": title.encode("utf-8"),
                "Priority": priority,
                "Tags": tags,
                "Click": url,
                "Actions": f"view, Apri TestFlight, {deep}, clear=true; "
                           f"view, Apri nel browser, {url}",
            }
            # Senza token ntfy.sh conta la quota giornaliera per IP, e i runner
            # GitHub escono da IP condivisi: un giorno di traffico altrui puo'
            # bruciare la quota proprio quando serve. Col token e' quota tua.
            if token_ntfy := os.environ.get("NTFY_TOKEN", "").strip():
                headers["Authorization"] = f"Bearer {token_ntfy}"
            req = urllib.request.Request(
                f"{server}/{topic}",
                data=message.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20):
                sent.append("ntfy")
        except Exception as e:  # noqa: BLE001
            print(f"  ! ntfy fallita: {e}", file=sys.stderr)
            failed.append("ntfy")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        payload = urllib.parse.urlencode(
            {
                "chat_id": chat,
                "text": telegram_body(title, message, url, tags, links, righe_stato),
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode()
        try:
            with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=20
            ):
                sent.append("telegram")
        except Exception as e:  # noqa: BLE001
            print(f"  ! telegram fallita: {e}", file=sys.stderr)
            failed.append("telegram")

    if sent:
        print(f"  -> notifica inviata via: {', '.join(sent)}")
    elif failed:
        print(f"  -> NOTIFICA FALLITA su: {', '.join(failed)}")
    else:
        print("  -> nessun canale di notifica configurato")
    return bool(sent) or not failed


def heartbeat_dovuto(now, last):
    """True se oggi tocca il battito e non e' ancora partito.

    Un battito "ogni N giorni" deriva: riparte dall'ultimo invio, e ogni giorno
    slitta di qualche minuto finche' non ti arriva alle tre di notte. Ancorarlo
    a un'ora del giorno lo tiene fermo.

    Niente aritmetica di fusi: si guarda l'ora locale, e si confrontano due
    date di calendario. Cosi' i due cambi d'ora dell'anno non sono un caso
    particolare da gestire, semplicemente non esistono.

    Il cron di GitHub arriva con 13-21 minuti di ritardo, quindi il battito
    delle 9:00 arriva davvero fra le 9:00 e le 9:25. Per un "sono vivo" va bene.
    """
    conf = os.environ.get("HEARTBEAT_HOUR", "9").strip()
    if not conf:  # stringa vuota = battito spento
        return False
    tz = ZoneInfo(os.environ.get("HEARTBEAT_TZ") or "Europe/Rome")
    adesso = datetime.fromtimestamp(now, tz)
    if adesso.hour < int(float(conf)):
        return False
    if not last:
        return True  # mai battuto: oggi si registra soltanto
    return datetime.fromtimestamp(last, tz).date() != adesso.date()


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    coppie = leggi_codici(os.environ.get("TF_CODES", ""))
    codes = [c for c, _ in coppie]
    nomi = dict(coppie)
    if not codes:
        print("TF_CODES non impostata: niente da controllare.", file=sys.stderr)
        return 1

    dry_run = "--dry-run" in sys.argv
    old = load_state()
    meta = old.pop("_meta", {}) if isinstance(old.get("_meta"), dict) else {}
    meta_before = dict(meta)
    new = {}
    now = int(time.time())

    for code in codes:
        url = f"https://testflight.apple.com/join/{code}"
        status, body = fetch(code)
        state, detail = classify(status, body)
        prev = old.get(code, {}).get("state")
        streak = old.get(code, {}).get("error_streak", 0)
        streak = streak + 1 if state == "ERROR" else 0
        new[code] = {
            "state": state,
            "detail": detail,
            "checked_at": now,
            "error_streak": streak,
        }

        # Apple can start refusing datacenter IPs. Say so instead of dying quietly.
        if streak == ERROR_STREAK_ALERT:
            notify(
                "Watcher in errore",
                f"{nomi[code]}: {ERROR_STREAK_ALERT} controlli falliti di fila. "
                f"Apple potrebbe bloccare gli IP dei runner GitHub.\n{detail}",
                url,
                "high",
                "warning",
            )

        print(f"[{code}] {prev or '-'} -> {state}: {detail}")

        if state == prev:
            continue

        delivered = True
        if state == "OPEN":
            delivered = notify(
                "SLOT TESTFLIGHT APERTO",
                f"{nomi[code]} sta accettando tester. Vai SUBITO.\n{detail}",
                url,
                priority="urgent",
                tags="rotating_light",
            )
        elif prev == "OPEN":
            delivered = notify(
                "Slot richiuso", f"{nomi[code]} non accetta piu' tester.\n{detail}",
                url, "low", "lock")
        elif state == "UNKNOWN":
            delivered = notify(
                "Stato TestFlight non riconosciuto",
                f"La pagina di {nomi[code]} non corrisponde a nessuno stato noto - "
                f"controlla a mano, potrebbe essere aperto.\n{detail}",
                url,
                "high",
                "warning",
            )
        elif state == "GONE" and prev:
            delivered = notify(
                "Codice invito sparito", f"{nomi[code]} ora risponde 404.", url, "default", "ghost")
        elif state == "ERROR" and prev not in (None, "ERROR"):
            print("  (errore transitorio, nessuna notifica)")

        # Se non siamo riusciti ad avvisare, NON registrare il nuovo stato:
        # al prossimo giro il cambiamento va rilevato di nuovo e riprovato.
        # Registrarlo qui significherebbe restare in silenzio per sempre.
        if not delivered:
            print(f"  ! notifica non consegnata: {code} resta a '{prev}', si riprova")
            if code in old:
                new[code] = dict(old[code])
            else:
                del new[code]

    if dry_run:
        print("\n--dry-run: stato NON salvato.")
        return 0

    # Periodic "still alive" ping: if GitHub silently disables the schedule,
    # the missing heartbeat is the only way you would ever find out.
    last_hb = meta.get("last_heartbeat", 0)
    if heartbeat_dovuto(now, last_hb):
        # Al primo giro in assoluto non si avvisa: non e' un battito, e' la
        # nascita. Si registra e basta, il primo vero battito e' domani.
        if last_hb:
            righe_stato = [
                (nomi[c], f"https://testflight.apple.com/join/{c}",
                 STATI.get(new[c]["state"], new[c]["state"]))
                for c in codes if c in new
            ]
            print("  " + "; ".join(f"{n}={s}" for n, _, s in righe_stato))
            notify("Watcher vivo", "",
                   f"https://testflight.apple.com/join/{codes[0]}",
                   "min", "heartbeat", righe_stato=righe_stato)
        meta["last_heartbeat"] = now

    new["_meta"] = meta

    # Anything that must survive to the next run makes this commit-worthy;
    # `checked_at` deliberately does not, or we would commit every 5 minutes.
    def signature(d):
        return {
            k: (v.get("state"), v.get("error_streak", 0))
            for k, v in d.items()
            if k != "_meta"
        } | {"_hb": d.get("_meta", {}).get("last_heartbeat", 0)}

    changed = signature(new) != signature(dict(old, _meta=meta_before))

    with open(STATE_FILE, "w") as f:
        json.dump(new, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"\nstate.json {'aggiornato' if changed else 'invariato'}.")
    # Tell the workflow whether it needs to commit.
    summary = " ".join(f"{c}={v['state']}" for c, v in sorted(new.items()) if c != "_meta")
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"summary={summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
