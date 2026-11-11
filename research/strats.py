"""Noyaux de backtest (numba). Bougies = prix bid ; le spread est appliqué explicitement :
un achat entre à l'ask (bid + spread) et sort au bid ; une vente entre au bid et sort à l'ask.
Quand le stop et l'objectif sont dans la même bougie, on compte le STOP (hypothèse prudente)."""
import numpy as np
from numba import njit


@njit(cache=True)
def pivots(h, l, n):
    """Sommets / creux stricts : extrême unique sur n bougies de chaque côté. Confirmé à l'indice p + n."""
    size = len(h)
    is_hi = np.zeros(size, np.bool_)
    is_lo = np.zeros(size, np.bool_)
    for i in range(n, size - n):
        ok_h, ok_l = True, True
        for j in range(i - n, i + n + 1):
            if j == i:
                continue
            if h[j] >= h[i]:
                ok_h = False
            if l[j] <= l[i]:
                ok_l = False
            if not ok_h and not ok_l:
                break
        is_hi[i] = ok_h
        is_lo[i] = ok_l
    return is_hi, is_lo


# --------------------------------------------------------------------------- gestion commune d'une position
@njit(cache=True)
def _exit_check(side, o, h, l, stop, target, spread, has_target, entry, risk, ev):
    """Retourne (sorti?, résultat en R). Achat : sortie au bid. Vente : sortie à l'ask.
    Stop ET objectif dans la même bougie : ev=False -> on compte le stop (prudent) ;
    ev=True -> espérance neutre (probabilité de toucher l'objectif d'abord = distance au stop / distance totale,
    mesurée depuis l'ouverture), ce qui ne crée ni avantage ni handicap artificiel."""
    if side > 0:
        s_hit = l <= stop
        t_hit = has_target and h >= target
        if s_hit and t_hit:
            if o <= stop:
                return True, (o - entry) / risk
            if o >= target or not ev:
                return True, ((target if o >= target else stop) - entry) / risk
            ds, dt = o - stop, target - o
            p = ds / (ds + dt)
            return True, (p * (target - entry) + (1 - p) * (stop - entry)) / risk
        if s_hit:
            return True, (min(stop, o) - entry) / risk
        if t_hit:
            return True, (target - entry) / risk
    else:
        oa = o + spread
        s_hit = h + spread >= stop
        t_hit = has_target and l + spread <= target
        if s_hit and t_hit:
            if oa >= stop:
                return True, (entry - oa) / risk
            if oa <= target or not ev:
                return True, (entry - (target if oa <= target else stop)) / risk
            ds, dt = stop - oa, oa - target
            p = ds / (ds + dt)
            return True, (p * (entry - target) + (1 - p) * (entry - stop)) / risk
        if s_hit:
            return True, (entry - max(stop, oa)) / risk
        if t_hit:
            return True, (entry - target) / risk
    return False, 0.0


# --------------------------------------------------------------------------- A. prise de liquidité (« turtle soup »)
@njit(cache=True)
def sweep_kernel(o, h, l, c, a, hi_act, hi_px, lo_act, lo_px, spread, rr, buf_atr, max_hold, min_risk_sp,
                 max_age, bias, use_bias, ev):
    """Niveaux = anciens sommets/creux (liquidité). Signal : la bougie dépasse le niveau puis CLÔTURE de l'autre côté.
    Entrée à l'ouverture suivante dans le sens du retournement, stop derrière la mèche, objectif = rr x le risque.
    hi_act[k] = indice de la bougie à la clôture de laquelle le niveau k devient connu (trié)."""
    n = len(o)
    cap = 4096
    ahp = np.empty(cap); aha = np.empty(cap, np.int64); nh = 0
    alp = np.empty(cap); ala = np.empty(cap, np.int64); nl = 0
    kh, kl = 0, 0
    e_i = np.empty(n, np.int64); x_i = np.empty(n, np.int64); sd = np.empty(n, np.int64)
    e_px = np.empty(n); rk = np.empty(n); rr_out = np.empty(n)
    nt = 0
    pos, entry, stop, target, risk, ent_i = 0, 0.0, 0.0, 0.0, 0.0, 0
    for i in range(1, n - 1):
        if pos != 0:
            done, res = _exit_check(pos, o[i], h[i], l[i], stop, target, spread, rr > 0, entry, risk, ev)
            if not done and i - ent_i >= max_hold:
                done, res = True, ((c[i] if pos > 0 else c[i] + spread) - entry) * pos / risk
            if done:
                e_i[nt] = ent_i; x_i[nt] = i; sd[nt] = pos; e_px[nt] = entry; rk[nt] = risk
                rr_out[nt] = res
                nt += 1
                pos = 0
        sig, sig_stop = 0, 0.0
        if not (np.isnan(a[i]) or a[i] <= 0):
            k = 0
            while k < nh:                         # sommets : liquidité au-dessus
                L = ahp[k]
                if h[i] > L:
                    if c[i] < L and sig == 0:
                        sig, sig_stop = -1, h[i] + buf_atr * a[i]
                    nh -= 1; ahp[k] = ahp[nh]; aha[k] = aha[nh]
                    continue
                if i - aha[k] > max_age:
                    nh -= 1; ahp[k] = ahp[nh]; aha[k] = aha[nh]
                    continue
                k += 1
            k = 0
            while k < nl:                         # creux : liquidité en dessous
                L = alp[k]
                if l[i] < L:
                    if c[i] > L and sig == 0:
                        sig, sig_stop = 1, l[i] - buf_atr * a[i]
                    nl -= 1; alp[k] = alp[nl]; ala[k] = ala[nl]
                    continue
                if i - ala[k] > max_age:
                    nl -= 1; alp[k] = alp[nl]; ala[k] = ala[nl]
                    continue
                k += 1
        if pos == 0 and sig != 0 and (not use_bias or bias[i] == sig):
            if sig > 0:
                ent = o[i + 1] + spread
                r = ent - sig_stop
            else:
                ent = o[i + 1]
                r = sig_stop - ent
            if r > 0 and r >= min_risk_sp * spread:
                pos, entry, stop, risk, ent_i = sig, ent, sig_stop, r, i + 1
                target = ent + sig * rr * r
        while kh < len(hi_act) and hi_act[kh] <= i:
            if nh < cap:
                ahp[nh] = hi_px[kh]; aha[nh] = i; nh += 1
            kh += 1
        while kl < len(lo_act) and lo_act[kl] <= i:
            if nl < cap:
                alp[nl] = lo_px[kl]; ala[nl] = i; nl += 1
            kl += 1
    return e_i[:nt], x_i[:nt], sd[:nt], e_px[:nt], rk[:nt], rr_out[:nt]


# --------------------------------------------------------------------------- B. retour sur la zone d'origine après cassure
@njit(cache=True)
def zone_kernel(o, h, l, c, a, n, spread, buf_atr, min_risk_sp, rr_min, rr_cap, rr_fixed, max_age, max_hold,
                entry_mode, bias, use_bias, ev):
    """Structure : sommets/creux de force n. Cassure haussière = clôture au-dessus du dernier sommet confirmé.
    Zone d'achat = la bougie du plus bas qui a lancé le mouvement : ordre limite à E, stop sous sa mèche.
      entry_mode 0 : E = bas du corps (le niveau « open/close » des captures) -> stop très serré
      entry_mode 1 : E = milieu de la bougie      entry_mode 2 : E = haut de la bougie (zone entière)
    Objectif = le plus haut atteint depuis (la liquidité d'en face), borné par rr_min / rr_cap ; ou rr_fixed x le risque.
    Une seule position à la fois ; premier retour sur la zone uniquement."""
    size = len(o)
    is_hi, is_lo = pivots(h, l, n)
    cap = 16
    zE = np.empty(cap); zS = np.empty(cap); zX = np.empty(cap); zB = np.empty(cap, np.int64); zD = np.empty(cap, np.int64)
    nz = 0
    e_i = np.empty(size, np.int64); x_i = np.empty(size, np.int64); sd = np.empty(size, np.int64)
    e_px = np.empty(size); rk = np.empty(size); rr_out = np.empty(size)
    nt = 0
    pos, entry, stop, target, risk, ent_i = 0, 0.0, 0.0, 0.0, 0.0, 0
    sh, sh_i, sh_ok = 0.0, -1, False
    sl, sl_i, sl_ok = 0.0, -1, False
    for i in range(2 * n + 1, size - 1):
        if pos != 0:
            done, res = _exit_check(pos, o[i], h[i], l[i], stop, target, spread, True, entry, risk, ev)
            if not done and i - ent_i >= max_hold:
                done, res = True, ((c[i] if pos > 0 else c[i] + spread) - entry) * pos / risk
            if done:
                e_i[nt] = ent_i; x_i[nt] = i; sd[nt] = pos; e_px[nt] = entry; rk[nt] = risk
                rr_out[nt] = res
                nt += 1
                pos = 0
        k = 0
        while k < nz:
            d, E, S = zD[k], zE[k], zS[k]
            remove = False
            if d > 0:
                touched = l[i] + spread <= E
                if touched:
                    remove = True
                    if pos == 0 and (not use_bias or bias[i] == 1):
                        fill = min(E, o[i] + spread)
                        r = fill - S
                        T = zX[k]
                        if rr_fixed > 0:
                            T = fill + rr_fixed * r
                        ok = r > 0 and r >= min_risk_sp * spread
                        if ok and rr_fixed <= 0:
                            rr_now = (T - fill) / r
                            if rr_now < rr_min:
                                ok = False
                            elif rr_now > rr_cap:
                                T = fill + rr_cap * r
                        if ok:
                            if l[i] <= S:                     # rempli puis stoppé dans la même bougie : certain
                                e_i[nt] = i; x_i[nt] = i; sd[nt] = 1; e_px[nt] = fill; rk[nt] = r
                                rr_out[nt] = -1.0
                                nt += 1
                            elif c[i] >= T:                   # clôture au-delà de l'objectif après le remplissage : certain
                                e_i[nt] = i; x_i[nt] = i; sd[nt] = 1; e_px[nt] = fill; rk[nt] = r
                                rr_out[nt] = (T - fill) / r
                                nt += 1
                            else:
                                pos, entry, stop, target, risk, ent_i = 1, fill, S, T, r, i
                elif c[i] < S or i - zB[k] > max_age:
                    remove = True
                else:
                    if h[i] > zX[k]:
                        zX[k] = h[i]
            else:
                touched = h[i] >= E
                if touched:
                    remove = True
                    if pos == 0 and (not use_bias or bias[i] == -1):
                        fill = max(E, o[i])
                        r = S - fill
                        T = zX[k]
                        if rr_fixed > 0:
                            T = fill - rr_fixed * r
                        ok = r > 0 and r >= min_risk_sp * spread
                        if ok and rr_fixed <= 0:
                            rr_now = (fill - T) / r
                            if rr_now < rr_min:
                                ok = False
                            elif rr_now > rr_cap:
                                T = fill - rr_cap * r
                        if ok:
                            if h[i] + spread >= S:
                                e_i[nt] = i; x_i[nt] = i; sd[nt] = -1; e_px[nt] = fill; rk[nt] = r
                                rr_out[nt] = -1.0
                                nt += 1
                            elif c[i] + spread <= T:
                                e_i[nt] = i; x_i[nt] = i; sd[nt] = -1; e_px[nt] = fill; rk[nt] = r
                                rr_out[nt] = (fill - T) / r
                                nt += 1
                            else:
                                pos, entry, stop, target, risk, ent_i = -1, fill, S, T, r, i
                elif c[i] > S or i - zB[k] > max_age:
                    remove = True
                else:
                    if l[i] < zX[k]:
                        zX[k] = l[i]
            if remove:
                nz -= 1
                zE[k] = zE[nz]; zS[k] = zS[nz]; zX[k] = zX[nz]; zB[k] = zB[nz]; zD[k] = zD[nz]
            else:
                k += 1
        p = i - n
        if is_hi[p]:
            sh, sh_i, sh_ok = h[p], p, True
        if is_lo[p]:
            sl, sl_i, sl_ok = l[p], p, True
        if np.isnan(a[i]) or a[i] <= 0:
            continue
        if sh_ok and c[i] > sh:                      # cassure haussière
            sh_ok = False
            q = sh_i
            for j in range(sh_i, i + 1):
                if l[j] < l[q]:
                    q = j
            S = l[q] - buf_atr * a[i]
            if entry_mode == 0:
                E = min(o[q], c[q])
            elif entry_mode == 1:
                E = 0.5 * (h[q] + l[q])
            else:
                E = h[q]
            hh = h[q]
            for j in range(q, i + 1):
                if h[j] > hh:
                    hh = h[j]
            if E < c[i] and nz < cap:
                zE[nz] = E; zS[nz] = S; zX[nz] = hh; zB[nz] = i; zD[nz] = 1; nz += 1
        if sl_ok and c[i] < sl:                      # cassure baissière
            sl_ok = False
            q = sl_i
            for j in range(sl_i, i + 1):
                if h[j] > h[q]:
                    q = j
            S = h[q] + buf_atr * a[i]
            if entry_mode == 0:
                E = max(o[q], c[q])
            elif entry_mode == 1:
                E = 0.5 * (h[q] + l[q])
            else:
                E = l[q]
            ll = l[q]
            for j in range(q, i + 1):
                if l[j] < ll:
                    ll = l[j]
            if E > c[i] and nz < cap:
                zE[nz] = E; zS[nz] = S; zX[nz] = ll; zB[nz] = i; zD[nz] = -1; nz += 1
    return e_i[:nt], x_i[:nt], sd[:nt], e_px[:nt], rk[:nt], rr_out[:nt]


# --------------------------------------------------------------------------- C. noyau générique : signaux -> trades
@njit(cache=True)
def generic_kernel(o, h, l, c, long_sig, short_sig, exit_long, exit_short, stop_dist, spread, target_r, max_hold,
                   trail, ev):
    """Signal à la clôture de i -> entrée à l'ouverture de i+1, stop initial = stop_dist[i].
    Sortie : stop touché, objectif (target_r x risque, 0 = aucun), signal de sortie à la clôture (sortie à l'ouverture
    suivante), ou durée max. trail > 0 : le stop suit le meilleur cours à trail x stop_dist initial."""
    n = len(o)
    e_i = np.empty(n, np.int64); x_i = np.empty(n, np.int64); sd = np.empty(n, np.int64)
    e_px = np.empty(n); rk = np.empty(n); rr_out = np.empty(n)
    nt = 0
    pos, entry, stop, target, risk, ent_i, best = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
    pending_exit = False
    for i in range(1, n - 1):
        if pos != 0:
            done, res = False, 0.0
            if pending_exit:
                done, res = True, ((o[i] if pos > 0 else o[i] + spread) - entry) * pos / risk
            else:
                done, res = _exit_check(pos, o[i], h[i], l[i], stop, target, spread, target_r > 0, entry, risk, ev)
                if not done and i - ent_i >= max_hold:
                    done, res = True, ((c[i] if pos > 0 else c[i] + spread) - entry) * pos / risk
            if done:
                e_i[nt] = ent_i; x_i[nt] = i; sd[nt] = pos; e_px[nt] = entry; rk[nt] = risk
                rr_out[nt] = res
                nt += 1
                pos = 0
                pending_exit = False
            else:
                if trail > 0:
                    if pos > 0:
                        if h[i] > best:
                            best = h[i]
                        if best - trail * risk > stop:
                            stop = best - trail * risk
                    else:
                        if l[i] < best:
                            best = l[i]
                        if best + spread + trail * risk < stop:
                            stop = best + spread + trail * risk
                if (pos > 0 and exit_long[i]) or (pos < 0 and exit_short[i]):
                    pending_exit = True
        if pos == 0:
            d = stop_dist[i]
            if np.isnan(d) or d <= 0:
                continue
            if long_sig[i]:
                ent = o[i + 1] + spread
                pos, entry, stop, risk, ent_i, best = 1, ent, ent - d, d, i + 1, ent
                target = ent + target_r * d
            elif short_sig[i]:
                ent = o[i + 1]
                pos, entry, stop, risk, ent_i, best = -1, ent, ent + d, d, i + 1, ent
                target = ent - target_r * d
    return e_i[:nt], x_i[:nt], sd[:nt], e_px[:nt], rk[:nt], rr_out[:nt]
