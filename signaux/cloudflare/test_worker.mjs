// Vérifie que la version Cloudflare donne EXACTEMENT les mêmes signaux que la version Python. node test_worker.mjs
import { readFileSync } from "node:fs";
import { detect, dueUnits, message } from "./worker.js";

let fail = 0;
const ok = (cond, what) => { if (!cond) { fail++; console.log("ÉCHEC", what); } };
const data = JSON.parse(readFileSync(new URL("./controle.json", import.meta.url)));
for (const [key, { bars, sigs }] of Object.entries(data)) {
  const all = bars.epoch.map((e, k) => ({ epoch: e, open: bars.open[k], high: bars.high[k], low: bars.low[k], close: bars.close[k] }));
  let same = 0, n = 0;
  for (let i = 150; i <= all.length; i++) {
    const js = detect(all.slice(i - 150, i));
    const py = sigs[i];
    if (!js && !py) continue;
    n++;
    if (js && py && js.sens === py[0] && Math.abs(js.stop - py[2]) < 1e-9 && Math.abs(js.prix - py[1]) < 1e-9) same++;
    else console.log("  différence", key, i, js && js.sens, py && py[0]);
  }
  console.log(`${key} : ${same}/${n} signaux identiques`);
  ok(same === n && n === Object.keys(sigs).length, key);
}
// calendrier : M15 traité 1 min après chaque quart d'heure, H1 2 min après l'heure, H4 3 min après 0h/4h/8h... UTC
const T = Date.UTC(2026, 10, 16, 8, 0, 0) / 1000;
ok(JSON.stringify(dueUnits(["M15", "H1", "H4"], T + 60)) === JSON.stringify([["M15", T - 900]]), "M15 à 08:01");
ok(JSON.stringify(dueUnits(["M15", "H1", "H4"], T + 120)) === JSON.stringify([["H1", T - 3600]]), "H1 à 08:02");
ok(JSON.stringify(dueUnits(["M15", "H1", "H4"], T + 180)) === JSON.stringify([["H4", T - 14400]]), "H4 à 08:03");
ok(dueUnits(["M15", "H1", "H4"], T + 300).length === 0, "rien à 08:05");
ok(dueUnits(["H4"], T + 3600 + 180).length === 0, "pas de H4 à 09:03");
ok(message("EUR/USD", "H1", { sens: "ACHAT", prix: 1.11654, stop: 1.1141, objectif: 1.12142, rsi: 61.2, epoch: 0 })
   .startsWith("🟢 ACHAT EUR/USD (H1)\nPrix : 1.11654\nStop proposé : 1.11410\nObjectif proposé : 1.12142"), "message");
console.log(fail ? `${fail} TEST(S) EN ÉCHEC` : "TOUS LES TESTS PASSENT");
process.exit(fail ? 1 : 0);
