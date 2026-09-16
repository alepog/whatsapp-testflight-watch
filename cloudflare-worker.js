/**
 * Variante Cloudflare Workers: stessa logica di check.py, ma il cron di
 * Cloudflare parte davvero al minuto, senza le code di GitHub Actions.
 *
 * Deploy:
 *   npm create cloudflare@latest wa-testflight -- --type=hello-world
 *   # sostituisci src/index.js con questo file, poi:
 *   npx wrangler kv namespace create STATE
 *   # incolla l'id in wrangler.toml, aggiungi il cron, poi:
 *   npx wrangler secret put NTFY_TOPIC
 *   npx wrangler deploy
 *
 * wrangler.toml:
 *   [triggers]
 *   crons = ["* * * * *"]
 *   [vars]
 *   TF_CODES = "krUFQpyJ,YcmGWyxV"
 *   [[kv_namespaces]]
 *   binding = "STATE"
 *   id = "<id-restituito-dal-comando-sopra>"
 *
 * Piano gratuito: 100.000 richieste al giorno, un controllo al minuto ne usa
 * ~1.440. Ci sta comodamente.
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

  if (/\bjoin the .+ beta\b/i.test(title)) return ["OPEN", detail];
  if (CLOSED_MARKERS.some((m) => hay.includes(m))) return ["CLOSED", detail];
  return ["UNKNOWN", detail];
}

async function notify(env, title, message, url, priority, tags) {
  if (!env.NTFY_TOPIC) return;
  await fetch(`${env.NTFY_SERVER || "https://ntfy.sh"}/${env.NTFY_TOPIC}`, {
    method: "POST",
    body: message,
    headers: {
      Title: title,
      Priority: priority,
      Tags: tags,
      Click: url,
    },
  });
}

async function checkAll(env) {
  const codes = (env.TF_CODES || "").split(",").map((c) => c.trim()).filter(Boolean);
  const results = [];

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
    const prev = await env.STATE.get(code);
    results.push({ code, prev, state, detail });

    if (state !== prev) {
      await env.STATE.put(code, state);
      if (state === "OPEN") {
        await notify(env, "SLOT TESTFLIGHT APERTO",
          `Il beta ${code} accetta tester. Vai SUBITO.\n${detail}`,
          url, "urgent", "rotating_light");
      } else if (prev === "OPEN") {
        await notify(env, "Slot richiuso",
          `${code} non accetta piu' tester.`, url, "low", "lock");
      } else if (state === "UNKNOWN") {
        await notify(env, "Stato TestFlight non riconosciuto",
          `${code}: pagina non riconosciuta, controlla a mano.\n${detail}`,
          url, "high", "warning");
      }
    }
  }
  return results;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(checkAll(env));
  },
  // Apri l'URL del worker nel browser per vedere lo stato e testare il deploy.
  async fetch(request, env) {
    const results = await checkAll(env);
    return new Response(JSON.stringify(results, null, 2), {
      headers: { "content-type": "application/json" },
    });
  },
};
