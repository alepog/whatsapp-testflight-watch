/**
 * Watcher slot TestFlight - versione Cloudflare Workers.
 *
 * Stessa logica di check.py, ma il cron di Cloudflare parte davvero ogni
 * minuto invece di finire nelle code di GitHub Actions.
 *
 * Si installa TUTTO dal browser, senza Node e senza wrangler: le istruzioni
 * passo passo sono in README.md, sezione "Cloudflare".
 *
 * Gli serve:
 *   - un binding KV chiamato  STATE   (per ricordare lo stato tra un giro e l'altro)
 *   - una variabile           TF_CODES = "krUFQpyJ,YcmGWyxV"
 *   - un secret               NTFY_TOPIC
 *   - opzionale               NTFY_TOKEN  (token di un account ntfy.sh)
 *   - opzionale               TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
 *   - un cron trigger         */5 * * * *
 */

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/17.0 Safari/605.1.15";

const CLOSED_MARKERS = [
  "isn't accepting any new testers",
  "this beta is full",
  "this beta has expired",
  "this beta isn't available",
];

const ERROR_STREAK_ALERT = 10; // giri falliti di fila prima di gridare
const HEARTBEAT_HOUR = 9; // ora locale del battito quotidiano
const HEARTBEAT_TZ = "Europe/Rome";

function stripTags(s) {
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

export function classify(status, body) {
  if (status === 404) return ["GONE", "404 - codice invito inesistente"];
  if (status !== 200) return ["ERROR", `HTTP ${status}`];

  const title = stripTags((body.match(/<title[^>]*>(.*?)<\/title>/is) || [, ""])[1]);
  const betaStatus = stripTags(
    (body.match(/<div class="beta-status">(.*?)<\/div>/is) || [, ""])[1]
  );
  const detail = betaStatus || title || "(nessun testo di stato)";
  const hay = `${title} ${betaStatus}`.toLowerCase();

  // Segnale positivo: Apple intitola "Join the <App> beta" quando e' aperto.
  if (/\bjoin the .+ beta\b/i.test(title)) return ["OPEN", detail];
  if (CLOSED_MARKERS.some((m) => hay.includes(m))) return ["CLOSED", detail];
  // Non corrisponde a niente di noto: avvisa comunque, mai restare in silenzio.
  return ["UNKNOWN", detail];
}

async function notifyNtfy(env, title, message, url, priority, tags) {
  if (!env.NTFY_TOPIC) return null;
  const deep = url.replace("https://", "itms-beta://");
  const headers = {
    Title: title,
    Priority: priority,
    Tags: tags,
    Click: url,
    Actions:
      `view, Apri TestFlight, ${deep}, clear=true; ` +
      `view, Apri nel browser, ${url}`,
  };
  // Senza token ntfy.sh conta la quota giornaliera per IP, e i Worker escono
  // da IP condivisi con la quota gia' esaurita da altri: da qui i 429. Con il
  // token di un account ntfy la quota diventa tua e il problema sparisce.
  if (env.NTFY_TOKEN) headers.Authorization = `Bearer ${env.NTFY_TOKEN}`;
  try {
    const r = await fetch(`${env.NTFY_SERVER || "https://ntfy.sh"}/${env.NTFY_TOPIC}`, {
      method: "POST",
      body: message,
      headers,
    });
    if (!r.ok) {
      console.log("ntfy ha risposto", r.status, (await r.text()).slice(0, 200));
      return `ntfy-http-${r.status}`;
    }
    return "ntfy";
  } catch (e) {
    console.log("ntfy fallita:", String(e));
    return "ntfy-errore";
  }
}

// Quale dei due watcher ha scritto. I messaggi arrivano sullo stesso bot, e
// senza etichetta non distingueresti un GitHub morto da un Cloudflare morto.
const FONTE = "CldF";

// Le stesse tag che ntfy usa per le sue icone, riusate come emoji su Telegram.
//
// La spunta e la croce rispondono a una domanda sola, a colpo d'occhio: il
// watcher sta facendo il suo lavoro? Il resto e' l'evento, non lo stato di
// salute, e ha un'icona sua.
const TG_EMOJI = {
  heartbeat: "\u2705",       // vivo e vegeto
  warning: "\u274C",         // non sta funzionando: guardaci
  ghost: "\u274C",           // codice invito morto: serve sostituirlo
  rotating_light: "\u{1F6A8}", // lo slot e' aperto
  lock: "\u{1F512}",           // lo slot si e' richiuso
  eyes: "\u{1F440}",
};

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// HTML e non Markdown: il testo di stato lo scrive Apple, e un underscore o un
// asterisco spaiato manderebbe in errore il parsing dell'intero messaggio.
function telegramBody(title, message, url, tags) {
  const emoji = TG_EMOJI[tags] || TG_EMOJI.eyes;
  const nl = message.indexOf("\n");
  const testa = nl === -1 ? message : message.slice(0, nl);
  const coda = nl === -1 ? "" : message.slice(nl + 1).trim();
  const righe = [`${emoji} <b>${esc(FONTE)} · ${esc(title)}</b>`, "", esc(testa)];
  // La coda e' il testo grezzo di Apple: in corsivo si legge come citazione.
  if (coda) righe.push(`<i>${esc(coda)}</i>`);
  righe.push("", `<a href="${esc(url)}">Apri in TestFlight</a>`);
  return righe.join("\n");
}

async function notifyTelegram(env, title, message, url, tags) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return null;
  try {
    const r = await fetch(
      `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          chat_id: env.TELEGRAM_CHAT_ID,
          text: telegramBody(title, message, url, tags),
          parse_mode: "HTML",
          disable_web_page_preview: true,
        }),
      }
    );
    if (!r.ok) {
      console.log("telegram ha risposto", r.status, (await r.text()).slice(0, 200));
      return `telegram-http-${r.status}`;
    }
    return "telegram";
  } catch (e) {
    console.log("telegram fallita:", String(e));
    return "telegram-errore";
  }
}

// Prova ogni canale configurato. Basta che UNO arrivi perche' la notifica sia
// consegnata; se falliscono tutti lo stato non viene salvato e si riprova.
async function notify(env, title, message, url, priority, tags) {
  const esiti = (
    await Promise.all([
      notifyNtfy(env, title, message, url, priority, tags),
      notifyTelegram(env, title, message, url, tags),
    ])
  ).filter((e) => e !== null);

  if (esiti.length === 0) return "non-configurato";
  const ok = esiti.filter((e) => e === "ntfy" || e === "telegram");
  return ok.length ? `inviata (${ok.join("+")})` : esiti.join(", ");
}

// True se oggi tocca il battito e non e' ancora partito.
//
// Un battito "ogni N giorni" deriva: riparte dall'ultimo invio e ogni giorno
// slitta di qualche minuto, finche' non ti arriva alle tre di notte. Ancorarlo
// a un'ora del giorno lo tiene fermo.
//
// Niente aritmetica di fusi: si guarda l'ora locale e si confrontano due date
// di calendario. Cosi' i due cambi d'ora dell'anno non sono un caso da gestire,
// semplicemente non esistono.
function battitoDovuto(nowMs, lastMs) {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: HEARTBEAT_TZ,
    hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
  });
  const leggi = (ms) => {
    const p = Object.fromEntries(
      fmt.formatToParts(new Date(ms)).map((x) => [x.type, x.value])
    );
    return { giorno: `${p.year}-${p.month}-${p.day}`, ora: Number(p.hour) };
  };
  const adesso = leggi(nowMs);
  if (adesso.ora < HEARTBEAT_HOUR) return false;
  if (!lastMs) return true; // mai battuto: oggi si registra soltanto
  return leggi(lastMs).giorno !== adesso.giorno;
}

async function checkAll(env) {
  const codes = (env.TF_CODES || "krUFQpyJ,YcmGWyxV")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  const results = [];
  const now = Date.now();

  for (const code of codes) {
    const url = `https://testflight.apple.com/join/${code}`;
    let status, body;
    try {
      const r = await fetch(url, {
        headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9" },
        cf: { cacheTtl: 0 },
      });
      status = r.status;
      body = await r.text();
    } catch (e) {
      status = 0;
      body = String(e);
    }

    const [state, detail] = classify(status, body);
    const saved = JSON.parse((await env.STATE.get(code)) || "{}");
    const prev = saved.state || null;
    const streak = state === "ERROR" ? (saved.error_streak || 0) + 1 : 0;
    let delivery = null;

    // Se Apple inizia a rifiutare gli IP di Cloudflare, dillo.
    if (streak === ERROR_STREAK_ALERT) {
      await notify(env, "Watcher Cloudflare in errore",
        `${code}: ${ERROR_STREAK_ALERT} controlli falliti di fila.\n${detail}`,
        url, "high", "warning");
    }

    if (state !== prev) {
      if (state === "OPEN") {
        delivery = await notify(env, "SLOT TESTFLIGHT APERTO",
          `Il beta ${code} accetta tester. Vai SUBITO.\n${detail}`,
          url, "urgent", "rotating_light");
      } else if (prev === "OPEN") {
        delivery = await notify(env, "Slot richiuso",
          `${code} non accetta piu' tester.`, url, "low", "lock");
      } else if (state === "UNKNOWN") {
        delivery = await notify(env, "Stato TestFlight non riconosciuto",
          `${code}: pagina non riconosciuta, controlla a mano.\n${detail}`,
          url, "high", "warning");
      } else if (state === "GONE" && prev) {
        delivery = await notify(env, "Codice invito sparito",
          `${code} ora risponde 404.`, url, "default", "ghost");
      }
    }

    // Se dovevamo avvisare e non ci siamo riusciti, NON registrare il nuovo
    // stato: al giro dopo il cambiamento va rilevato di nuovo e riprovato.
    // Registrarlo qui significherebbe tacere per sempre.
    const stuck =
      delivery !== null &&
      !delivery.startsWith("inviata") &&
      delivery !== "non-configurato";
    results.push({ code, prev, state, detail, notifica: delivery, riprovera: stuck });

    if (!stuck && (state !== prev || streak !== (saved.error_streak || 0))) {
      await env.STATE.put(code, JSON.stringify({ state, error_streak: streak, at: now }));
    }
  }

  // Battito quotidiano con titolo distinto da quello di GitHub: cosi' capisci
  // QUALE dei due watcher e' morto, non solo che ne e' morto uno.
  const lastHb = Number((await env.STATE.get("_heartbeat")) || 0);
  if (battitoDovuto(now, lastHb)) {
    // Al primo giro in assoluto non si avvisa: e' la nascita, non un battito.
    if (lastHb) {
      await notify(env, "Watcher Cloudflare vivo",
        results.map((r) => `${r.code}=${r.state}`).join(", "),
        "https://testflight.apple.com/", "min", "heartbeat");
    }
    await env.STATE.put("_heartbeat", String(now));
  }

  return results;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(checkAll(env));
  },
  // Apri l'URL del worker nel browser per vedere lo stato e provare il deploy.
  async fetch(request, env) {
    const results = await checkAll(env);
    return new Response(JSON.stringify(results, null, 2), {
      headers: { "content-type": "application/json" },
    });
  },
};
