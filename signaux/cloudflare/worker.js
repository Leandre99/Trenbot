/*
  Bot de SIGNAUX pour Cloudflare Workers (gratuit, sans carte, tourne sans ton PC).
  Il ne prend aucune position : il t'envoie un message Telegram quand ta stratégie donne un signal.

  Stratégie (à la clôture de chaque bougie) :
    ACHAT : le RSI 14 est passé sous 30 dans les 20 dernières bougies, puis la MM8 passe au-dessus de la MM21,
            les deux au-dessus de la MM50, et le prix clôture au-dessus de la MM50.
    VENTE : l'inverse (RSI au-dessus de 70, MM8 sous la MM21, les deux sous la MM50, prix sous la MM50).
    Le message propose un stop (plus bas / plus haut des 10 dernières bougies) et un objectif (2 fois le risque).

  Réglages : le bloc REGLAGES ci-dessous. Secrets (Cloudflare > Settings > Variables and Secrets) :
    TELEGRAM_TOKEN   = jeton donné par @BotFather
    TELEGRAM_CHAT_ID = identifiant de ta discussion avec ton bot
  Déclencheur (Settings > Triggers > Cron Triggers) : * * * * *   (chaque minute)
  Essai : ouvre  https://<ton-worker>.workers.dev/test?cle=<TELEGRAM_CHAT_ID>  -> message d'essai sur Telegram.
*/

const REGLAGES = {
  // nom affiché -> code Deriv
  marches: {
    "Or": "frxXAUUSD",
    "Step Index": "stpRNG",
    "Volatility 10": "R_10","Volatility 15": "R_15", "Volatility 25": "R_25", "Volatility 50": "R_50", "Volatility 75": "R_75",
    "Volatility 100": "R_100",
    "Volatility 10 (1s)": "1HZ10V", "Volatility 15 (1s)": "1HZ15V", "Volatility 25 (1s)": "1HZ25V",
    "Volatility 50 (1s)": "1HZ50V", "Volatility 75 (1s)": "1HZ75V", "Volatility 100 (1s)": "1HZ100V",
  },
  // absents de l'API publique de Deriv : CAD/CHF, CAD/JPY, CHF/JPY, Volatility 150 (1s)
  unites: ["M15", "M30", "H1", "H4"],    // au choix : M5 M15 M30 H1 H4 D1
  mm_rapide: 8, mm_moyenne: 21, mm_lente: 50,
  rsi_periode: 14, rsi_bas: 30, rsi_haut: 70,
  rsi_memoire: 20,                       // la survente / le surachat doit dater de moins de N bougies
  stop_bougies: 10,                      // stop proposé : plus bas / plus haut des N dernières bougies
  objectif_r: 2,                         // objectif proposé : N fois la distance au stop (0 = pas d'objectif)
};

const GRAN = { M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400, D1: 86400 };
// minutes d'attente après la clôture : laisse Deriv finaliser la bougie, et une seule unité par minute
// (M15 à :01 :16 :31 :46, M30 à :02 :32, H1 à :03, H4 à :04, D1 à 00:05) pour rester dans les limites gratuites
const DELAI = { M5: 1, M15: 1, M30: 2, H1: 3, H4: 4, D1: 5 };
const NB_BOUGIES = 150;
const DERIV = "api.derivws.com/trading/v1/options/ws/public";

// ------------------------------------------------------------------ calendrier
export function dueUnits(unites, nowSec) {
  // unités dont la bougie s'est fermée il y a exactement DELAI minutes ; retourne [unité, ouverture de cette bougie]
  const out = [];
  for (const tf of unites) {
    const g = GRAN[tf];
    if (!g) continue;
    const t = Math.floor(nowSec / 60) * 60 - DELAI[tf] * 60;           // instant de clôture visé
    if (t % g === 0) out.push([tf, t - g]);
  }
  return out;
}

// ------------------------------------------------------------------ indicateurs
function sma(c, n, i) {
  if (i + 1 < n) return NaN;
  let s = 0;
  for (let k = i - n + 1; k <= i; k++) s += c[k];
  return s / n;
}

export function rsiSeries(c, n) {
  // même calcul que pandas : moyenne exponentielle (alpha = 1/n, adjust=False) des hausses et des baisses
  const out = new Array(c.length).fill(NaN);
  let up = NaN, dn = NaN;
  const a = 1 / n;
  for (let i = 1; i < c.length; i++) {
    const d = c[i] - c[i - 1];
    const u = Math.max(d, 0), v = Math.max(-d, 0);
    if (i === 1) { up = u; dn = v; } else { up = (1 - a) * up + a * u; dn = (1 - a) * dn + a * v; }
    out[i] = dn === 0 ? NaN : 100 - 100 / (1 + up / dn);
  }
  return out;
}

export function detect(bars, p = REGLAGES) {
  // bars = bougies TERMINÉES [{epoch, open, high, low, close}] ; signal sur la dernière, ou null
  const n = bars.length;
  if (n < p.mm_lente + p.rsi_memoire + 2) return null;
  const c = bars.map(b => b.close);
  const align = i => {
    const f = sma(c, p.mm_rapide, i), m = sma(c, p.mm_moyenne, i), s = sma(c, p.mm_lente, i);
    return { up: f > m && m > s && c[i] > s, dn: f < m && m < s && c[i] < s };
  };
  const now = align(n - 1), prev = align(n - 2);
  const r = rsiSeries(c, p.rsi_periode).slice(n - p.rsi_memoire);
  const rmin = Math.min(...r.map(x => (Number.isNaN(x) ? Infinity : x)));
  const rmax = Math.max(...r.map(x => (Number.isNaN(x) ? -Infinity : x)));
  const price = c[n - 1];
  const last = bars.slice(n - p.stop_bougies);
  let side, stop;
  if (now.up && !prev.up && rmin < p.rsi_bas) { side = 1; stop = Math.min(...last.map(b => b.low)); }
  else if (now.dn && !prev.dn && rmax > p.rsi_haut) { side = -1; stop = Math.max(...last.map(b => b.high)); }
  else return null;
  const risk = (price - stop) * side;
  if (!(risk > 0)) return null;
  const rl = rsiSeries(c, p.rsi_periode)[n - 1];
  return { sens: side > 0 ? "ACHAT" : "VENTE", prix: price, stop,
           objectif: p.objectif_r > 0 ? price + side * p.objectif_r * risk : null, rsi: rl, epoch: bars[n - 1].epoch };
}

const fmt = x => (x < 10 ? x.toFixed(5) : x < 1000 ? x.toFixed(3) : x.toFixed(2));

export function message(name, tf, sig) {
  const icon = sig.sens === "ACHAT" ? "🟢" : "🔴";
  const close = new Date((sig.epoch + GRAN[tf]) * 1000);
  const hh = String(close.getUTCHours()).padStart(2, "0"), mm = String(close.getUTCMinutes()).padStart(2, "0");
  const dd = String(close.getUTCDate()).padStart(2, "0"), mo = String(close.getUTCMonth() + 1).padStart(2, "0");
  const lines = [`${icon} ${sig.sens} ${name} (${tf})`, `Prix : ${fmt(sig.prix)}`, `Stop proposé : ${fmt(sig.stop)}`];
  if (sig.objectif !== null) lines.push(`Objectif proposé : ${fmt(sig.objectif)}`);
  lines.push(`RSI : ${Math.round(sig.rsi)}`, `Bougie fermée à ${dd}/${mo} ${hh}:${mm} UTC`);
  return lines.join("\n");
}

// ------------------------------------------------------------------ données Deriv (API publique)
async function openSocket() {
  if (typeof WebSocketPair !== "undefined") {                       // Cloudflare Workers
    const r = await fetch("https://" + DERIV, { headers: { Upgrade: "websocket" } });
    if (!r.webSocket) throw new Error(`Deriv : connexion refusée (${r.status})`);
    r.webSocket.accept();
    return r.webSocket;
  }
  const ws = new WebSocket("wss://" + DERIV);                       // Node (tests sur le PC)
  await new Promise((ok, ko) => { ws.addEventListener("open", ok); ws.addEventListener("error", ko); });
  return ws;
}

export async function fetchCandles(requests) {
  // requests = [[code, granularité], ...] -> Map "code|g" -> bougies (toutes, y compris celle en cours)
  const ws = await openSocket();
  const out = new Map();
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 25000);
    ws.addEventListener("message", ev => {
      const m = JSON.parse(typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data));
      const req = requests[(m.req_id || 0) - 1];
      if (!req) return;
      out.set(req.join("|"), m.error ? [] : (m.candles || []));
      if (out.size === requests.length) { clearTimeout(timer); resolve(); }
    });
    requests.forEach(([code, g], k) => ws.send(JSON.stringify({
      ticks_history: code, adjust_start_time: 1, count: NB_BOUGIES, end: "latest", granularity: g,
      style: "candles", req_id: k + 1 })));
  });
  try { ws.close(); } catch (e) { /* déjà fermée */ }
  return out;
}

// ------------------------------------------------------------------ Telegram
export async function telegram(env, text) {
  if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_CHAT_ID) throw new Error("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant");
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text }) });
  if (!r.ok) throw new Error(`Telegram a refusé le message (${r.status})`);
}

// ------------------------------------------------------------------ un passage
export async function runOnce(env, nowSec, send = true) {
  const due = dueUnits(REGLAGES.unites, nowSec);
  if (!due.length) return [];
  const reqs = [];
  for (const [tf] of due) for (const code of Object.values(REGLAGES.marches)) reqs.push([code, GRAN[tf]]);
  const data = await fetchCandles(reqs);
  const found = [];
  for (const [tf, lastOpen] of due) {
    const g = GRAN[tf];
    for (const [name, code] of Object.entries(REGLAGES.marches)) {
      const bars = (data.get(`${code}|${g}`) || []).filter(b => b.epoch + g <= nowSec)
        .map(b => ({ epoch: b.epoch, open: +b.open, high: +b.high, low: +b.low, close: +b.close }));
      if (!bars.length || bars[bars.length - 1].epoch !== lastOpen) continue;   // marché fermé : rien de périmé
      const sig = detect(bars);
      if (!sig) continue;
      const text = message(name, tf, sig);
      found.push(text);
      if (send) await telegram(env, text);
    }
  }
  return found;
}

// ------------------------------------------------------------------ réveil de GitHub
// Deriv refuse les serveurs de Cloudflare (429), et GitHub lance ses passages programmés très irrégulièrement.
// Solution : Cloudflare sert d'horloge fiable et demande à GitHub un passage 1 minute après chaque quart d'heure
// (:01 :16 :31 :46), c'est-à-dire juste après la clôture des bougies M15, M30, H1 et H4.
// Secret nécessaire : GITHUB_TOKEN (jeton GitHub « fine-grained », droit Actions en écriture sur le dépôt Trenbot).
const GITHUB_WORKFLOW = "https://api.github.com/repos/Leandre99/Trenbot/actions/workflows/signaux.yml/dispatches";

export function githubDue(nowSec) {
  return Math.floor(nowSec / 60) % 15 === 1;
}

export async function wakeGithub(env) {
  const r = await fetch(GITHUB_WORKFLOW, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "signaux-trendbot", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }) });
  if (r.status !== 204) throw new Error(`GitHub a refusé le lancement (${r.status}) ${(await r.text()).slice(0, 200)}`);
  console.log("passage GitHub demandé");
}

export default {
  async scheduled(event, env, ctx) {
    const now = Math.floor(event.scheduledTime / 1000);
    if (env.GITHUB_TOKEN) {
      if (githubDue(now)) ctx.waitUntil(wakeGithub(env));
      return;
    }
    ctx.waitUntil(runOnce(env, now));                 // ancien mode (bloqué par Deriv depuis Cloudflare)
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/test") {
      if (!env.TELEGRAM_CHAT_ID || url.searchParams.get("cle") !== String(env.TELEGRAM_CHAT_ID))
        return new Response("clé absente ou incorrecte", { status: 403 });
      try {
        await telegram(env, "🔔 Essai : le bot de signaux est branché, les signaux arriveront ici.");
        return new Response("Message d'essai envoyé sur Telegram.");
      } catch (e) {
        return new Response("ÉCHEC : " + e.message, { status: 500 });
      }
    }
    return new Response(`Bot de signaux actif : ${Object.keys(REGLAGES.marches).length} marchés, unités ${REGLAGES.unites.join(", ")}.`);
  },
};
