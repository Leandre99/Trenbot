// Passage réel sur les données Deriv, SANS envoyer de message (vérification sur le PC)
import { runOnce, fetchCandles, dueUnits } from "./worker.js";
const now = Math.floor(Date.now() / 1000);
const h4 = Math.floor(now / 14400) * 14400 + 180;            // 3 min après la dernière clôture H4
const t0 = Date.now();
const found = await runOnce({}, h4, false);
console.log(`passage H4 simulé à ${new Date(h4 * 1000).toISOString()} : ${found.length} signal(aux) en ${Date.now() - t0} ms`);
for (const m of found) console.log(m.replace(/\n/g, " | "));
const data = await fetchCandles([["frxEURUSD", 900], ["R_75", 3600], ["1HZ100V", 900], ["stpRNG", 14400], ["frxXAUUSD", 3600]]);
for (const [k, v] of data) console.log(k, v.length, "bougies, dernière :", v.length ? new Date(v[v.length - 1].epoch * 1000).toISOString() : "-");
process.exit(0);
