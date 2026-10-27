"""Interface de trendbot (Windows) : démarrer / arrêter le bot, journal en direct, positions, bilan, réglages.

Lancer : python app.py        (ou double-clic sur lancer_interface.bat)
Le bot tourne dans un processus à part : fermer l'interface ne coupe pas tes stop-loss (ils sont chez le broker).
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import config

HERE = Path(__file__).parent
SETTINGS = HERE / "settings.json"
FIELDS = [  # (clé, libellé, aide)
    ("CAPITAL_CAP", "Capital simulé ($)", "le bot raisonne comme si le compte valait ce montant + ses gains/pertes (vide = capital réel)"),
    ("RISK_PCT", "Risque par trade (%)", "perte visée si le stop est touché"),
    ("MAX_RISK_PCT", "Risque max au lot minimum (%)", "au-delà, le trade est refusé"),
    ("MAX_POSITIONS", "Positions max", "positions ouvertes en même temps"),
    ("DAILY_LOSS_STOP_PCT", "Arrêt du jour (%)", "plus de nouveau trade si le capital baisse de ce %"),
    ("MAX_SPREAD_R", "Spread max (en R)", "refus si le spread dépasse ce multiple de la distance au stop"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("trendbot")
        self.geometry("1000x720")
        self.minsize(820, 560)
        self.proc: subprocess.Popen | None = None
        self.mode = ""
        self.q: queue.Queue = queue.Queue()
        self.mt5 = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self.pump_log)
        self.after(500, self.refresh)

    # ------------------------------------------------------------ construction
    def _build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.lbl_account = ttk.Label(top, text="Compte : MT5 non connecté", font=("Segoe UI", 11, "bold"))
        self.lbl_account.pack(anchor="w")
        self.lbl_bot = ttk.Label(top, text="Bot : arrêté", font=("Segoe UI", 11))
        self.lbl_bot.pack(anchor="w", pady=(2, 8))

        bar = ttk.Frame(top)
        bar.pack(fill="x")
        self.btn_dry = ttk.Button(bar, text="▶ Démarrer (essai à blanc)", command=lambda: self.start(False))
        self.btn_trade = ttk.Button(bar, text="▶ Démarrer (trade sur la démo)", command=lambda: self.start(True))
        self.btn_stop = ttk.Button(bar, text="■ Arrêter", command=self.stop, state="disabled")
        self.btn_dry.pack(side="left", padx=(0, 6))
        self.btn_trade.pack(side="left", padx=(0, 6))
        self.btn_stop.pack(side="left", padx=(0, 18))
        ttk.Button(bar, text="Bilan", command=self.report).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Mettre à jour les lignes MT5", command=self.lines).pack(side="left", padx=(0, 6))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # onglet Journal
        f1 = ttk.Frame(nb)
        nb.add(f1, text="Journal")
        self.log = scrolledtext.ScrolledText(f1, state="disabled", font=("Consolas", 9), wrap="none")
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("err", foreground="#c0392b")
        self.log.tag_config("sig", foreground="#1e8449")
        self.log.tag_config("ref", foreground="#b9770e")
        self.log.tag_config("dim", foreground="#7f8c8d")

        # onglet Positions
        f2 = ttk.Frame(nb)
        nb.add(f2, text="Positions du bot")
        cols = ("marché", "sens", "lots", "stop", "gain/perte $")
        self.tree = ttk.Treeview(f2, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (220, 80, 80, 120, 120)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="x", padx=6, pady=6)
        self.lbl_pos = ttk.Label(f2, text="")
        self.lbl_pos.pack(anchor="w", padx=6)

        # onglet Réglages
        f3 = ttk.Frame(nb, padding=12)
        nb.add(f3, text="Réglages")
        self.entries = {}
        for r, (key, label, hint) in enumerate(FIELDS):
            ttk.Label(f3, text=label).grid(row=r, column=0, sticky="w", pady=4)
            var = tk.StringVar(value="" if getattr(config, key) is None else str(getattr(config, key)))
            ttk.Entry(f3, textvariable=var, width=12).grid(row=r, column=1, padx=10)
            ttk.Label(f3, text=hint, foreground="#7f8c8d").grid(row=r, column=2, sticky="w")
            self.entries[key] = var
        ttk.Button(f3, text="Enregistrer", command=self.save_settings).grid(row=len(FIELDS), column=0, pady=14, sticky="w")
        ttk.Label(f3, text="S'applique au prochain démarrage du bot. Marchés suivis : 24 (voir config.py).",
                  foreground="#7f8c8d").grid(row=len(FIELDS), column=1, columnspan=2, sticky="w")

    # ------------------------------------------------------------ journal
    def add_log(self, text: str):
        tag = ("err" if ("ERROR" in text or "ÉCHEC" in text or "Traceback" in text or "INVALIDE" in text)
               else "sig" if ("SIGNAL" in text or "ORDRE OK" in text or "ESSAI À BLANC]" in text)
               else "ref" if ("REFUSÉ" in text or "WARNING" in text)
               else "dim" if ("passage" in text or "exportées" in text) else "")
        self.log.config(state="normal")
        self.log.insert("end", text.rstrip("\n") + "\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 3000:
            self.log.delete("1.0", "500.0")
        self.log.see("end")
        self.log.config(state="disabled")

    def pump_log(self):
        try:
            while True:
                self.add_log(self.q.get_nowait())
        except queue.Empty:
            pass
        if self.proc is not None and self.proc.poll() is not None:
            self.add_log(f"--- le bot s'est arrêté (code {self.proc.returncode}) ---")
            self.proc, self.mode = None, ""
            self.update_buttons()
        self.after(200, self.pump_log)

    def _reader(self, proc):
        for line in proc.stdout:
            self.q.put(line)

    # ------------------------------------------------------------ actions
    def _spawn(self, args: list[str]):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        exe = sys.executable.replace("pythonw.exe", "python.exe")   # lancé par double-clic : le bot a besoin de python.exe
        p = subprocess.Popen([exe, "-u", *args], cwd=HERE, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             creationflags=flags)
        threading.Thread(target=self._reader, args=(p,), daemon=True).start()
        return p

    def start(self, trade: bool):
        if self.proc is not None:
            return
        if trade and not messagebox.askyesno(
                "Trader sur la démo",
                "Le bot va ouvrir de VRAIS ordres sur le compte DÉMO connecté à MT5 (il refuse un compte réel).\n\n"
                "Les stop-loss sont posés chez le broker. Continuer ?"):
            return
        self.mode = "trade sur la démo" if trade else "essai à blanc"
        self.add_log(f"=== démarrage : {self.mode} ===")
        self.proc = self._spawn(["live_mt5.py"] + (["--trade"] if trade else []))
        self.update_buttons()

    def stop(self):
        if self.proc is None:
            return
        self.proc.terminate()
        self.add_log("=== arrêt demandé (les positions ouvertes gardent leur stop-loss) ===")

    def lines(self):
        if self.proc is not None:
            messagebox.showinfo("Bot en marche", "Le bot met déjà les lignes à jour à chaque heure.")
            return
        self.add_log("=== mise à jour des lignes de tendance pour MT5 ===")
        self.proc = self._spawn(["live_mt5.py", "--lines-only", "--once"])
        self.mode = "mise à jour des lignes"
        self.update_buttons()

    def report(self):
        try:
            out = subprocess.run([sys.executable.replace("pythonw.exe", "python.exe"), "report.py", "30"], cwd=HERE,
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                 env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            text = (out.stdout + out.stderr).strip() or "(rien)"
        except Exception as e:  # noqa: BLE001
            text = f"Erreur : {e}"
        w = tk.Toplevel(self)
        w.title("Bilan des 30 derniers jours")
        w.geometry("640x420")
        t = scrolledtext.ScrolledText(w, font=("Consolas", 10))
        t.pack(fill="both", expand=True)
        t.insert("end", text)
        t.config(state="disabled")

    def save_settings(self):
        data = {}
        try:
            for key, var in self.entries.items():
                s = var.get().strip().replace(",", ".")
                if s == "":
                    if key != "CAPITAL_CAP":
                        raise ValueError(f"{key} ne peut pas être vide")
                    data[key] = None
                else:
                    v = float(s)
                    data[key] = int(v) if key == "MAX_POSITIONS" else v
            if data["MAX_POSITIONS"] < 1 or data["RISK_PCT"] <= 0 or data["RISK_PCT"] > 5:
                raise ValueError("positions >= 1 et risque entre 0 et 5 %")
        except ValueError as e:
            messagebox.showerror("Valeur invalide", str(e))
            return
        SETTINGS.write_text(json.dumps(data, indent=1), encoding="utf-8")
        messagebox.showinfo("Enregistré", "Réglages enregistrés. Ils s'appliqueront au prochain démarrage du bot.")

    def update_buttons(self):
        running = self.proc is not None
        for b in (self.btn_dry, self.btn_trade):
            b.config(state="disabled" if running else "normal")
        self.btn_stop.config(state="normal" if running else "disabled")
        self.lbl_bot.config(text=f"Bot : en marche ({self.mode})" if running else "Bot : arrêté",
                            foreground="#1e8449" if running else "")

    # ------------------------------------------------------------ MT5 (compte + positions)
    def refresh(self):
        try:
            if self.mt5 is None:
                import MetaTrader5 as mt5
                self.mt5 = mt5
            mt5 = self.mt5
            ti = mt5.terminal_info()
            if ti is None or not ti.connected:
                if not mt5.initialize():
                    raise RuntimeError("MT5 fermé ou non connecté")
            acc = mt5.account_info()
            demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            self.lbl_account.config(
                text=f"Compte {acc.login} · {acc.server} · {'DÉMO' if demo else 'RÉEL (le bot refusera de trader)'} · "
                     f"solde {acc.balance:.2f} {acc.currency} · capital simulé du bot : "
                     f"{config.CAPITAL_CAP if config.CAPITAL_CAP else 'réel'}")
            self.tree.delete(*self.tree.get_children())
            pos = [p for p in (mt5.positions_get() or []) if p.magic == config.MAGIC]
            for p in pos:
                self.tree.insert("", "end", values=(p.symbol, "ACHAT" if p.type == mt5.POSITION_TYPE_BUY else "VENTE",
                                                    p.volume, p.sl, f"{p.profit + p.swap:+.2f}"))
            self.lbl_pos.config(text=f"{len(pos)} position(s) ouverte(s) par le bot (max {config.MAX_POSITIONS}).")
        except Exception as e:  # noqa: BLE001
            self.lbl_account.config(text=f"Compte : MT5 non connecté ({e})")
        self.after(10_000, self.refresh)

    def on_close(self):
        if self.proc is not None:
            if not messagebox.askyesno("Quitter", "Le bot tourne encore. Quitter l'arrête.\n"
                                       "Tes positions ouvertes gardent leur stop-loss chez le broker.\n\nQuitter ?"):
                return
            self.proc.terminate()
        self.destroy()


if __name__ == "__main__":
    app = App()
    if "--smoke" in sys.argv:           # test de démarrage : construit l'interface, la rafraîchit une fois, quitte
        import time
        app.update()
        app.refresh()
        app.update()
        print("interface OK | compte :", app.lbl_account.cget("text"))
        app.start(False)                                   # démarre vraiment le bot (essai à blanc)
        t0 = time.time()
        while time.time() - t0 < 25:
            app.update()
            time.sleep(0.1)
        log = app.log.get("1.0", "end")
        assert "Compte" in log and "ESSAI À BLANC" in log, "le journal n'a pas reçu la sortie du bot"
        assert app.proc is not None and "en marche" in app.lbl_bot.cget("text")
        print("démarrage du bot depuis l'interface : OK (journal reçu)")
        app.stop()
        t0 = time.time()
        while app.proc is not None and time.time() - t0 < 15:
            app.update()
            time.sleep(0.1)
        assert app.proc is None and app.lbl_bot.cget("text") == "Bot : arrêté", "le bot ne s'est pas arrêté"
        print("arrêt du bot depuis l'interface : OK")
        app.report()
        app.update()
        print("bilan : OK")
        app.destroy()
    else:
        app.mainloop()
