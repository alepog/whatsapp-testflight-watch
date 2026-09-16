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

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

# Consecutive failed checks before we warn that the watcher itself is broken.
ERROR_STREAK_ALERT = int(os.environ.get("ERROR_STREAK_ALERT", "6"))


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


def notify(title, message, url, priority="default", tags="eyes"):
    sent = []

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        req = urllib.request.Request(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": priority,
                "Tags": tags,
                "Click": url,
                "Actions": f"view, Apri TestFlight, {url}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20):
                sent.append("ntfy")
        except Exception as e:  # noqa: BLE001
            print(f"  ! ntfy fallita: {e}", file=sys.stderr)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        payload = urllib.parse.urlencode(
            {
                "chat_id": chat,
                "text": f"*{title}*\n{message}\n{url}",
                "parse_mode": "Markdown",
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

    print(f"  -> notifica inviata via: {', '.join(sent) if sent else 'NESSUN CANALE CONFIGURATO'}")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    codes = [c.strip() for c in os.environ.get("TF_CODES", "").split(",") if c.strip()]
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
                f"{code}: {ERROR_STREAK_ALERT} controlli falliti di fila. "
                f"Apple potrebbe bloccare gli IP dei runner GitHub.\n{detail}",
                url,
                "high",
                "warning",
            )

        print(f"[{code}] {prev or '-'} -> {state}: {detail}")

        if state == prev:
            continue

        if state == "OPEN":
            notify(
                "SLOT TESTFLIGHT APERTO",
                f"Il beta {code} sta accettando tester. Vai SUBITO.\n{detail}",
                url,
                priority="urgent",
                tags="rotating_light",
            )
        elif prev == "OPEN":
            notify("Slot richiuso", f"Il beta {code} non accetta piu' tester.\n{detail}", url, "low", "lock")
        elif state == "UNKNOWN":
            notify(
                "Stato TestFlight non riconosciuto",
                f"La pagina di {code} non corrisponde a nessuno stato noto - "
                f"controlla a mano, potrebbe essere aperto.\n{detail}",
                url,
                "high",
                "warning",
            )
        elif state == "GONE" and prev:
            notify("Codice invito sparito", f"{code} ora risponde 404.", url, "default", "ghost")
        elif state == "ERROR" and prev not in (None, "ERROR"):
            print("  (errore transitorio, nessuna notifica)")

    if dry_run:
        print("\n--dry-run: stato NON salvato.")
        return 0

    # Periodic "still alive" ping: if GitHub silently disables the schedule,
    # the missing heartbeat is the only way you would ever find out.
    hb_days = float(os.environ.get("HEARTBEAT_DAYS", "0") or 0)
    last_hb = meta.get("last_heartbeat", 0)
    if hb_days > 0 and now - last_hb >= hb_days * 86400:
        if last_hb:
            alive = ", ".join(f"{c}={v['state']}" for c, v in sorted(new.items()))
            notify("Watcher vivo", f"Controllo regolare in corso.\n{alive}",
                   "https://testflight.apple.com/", "min", "heartbeat")
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
