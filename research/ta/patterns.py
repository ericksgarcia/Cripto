"""Detectores de padrões gráficos (análise técnica "profissional") em arrays OHLCV, sem look-ahead.

Cada detector devolve (sig, stop): sig[t]=True se o padrão se confirma no FECHAMENTO da barra t (entrada na abertura
de t+1); stop[t] = nível técnico de invalidação (ex.: abaixo do último fundo). Pivôs (topos/fundos) só ficam
disponíveis k barras depois de formados (confirmação), como um trader veria em tempo real.
"""
import numpy as np
from numba import njit


# ------------------------------------------------------------------ indicadores básicos
@njit(cache=True)
def ema(x, n):
    out = np.full(len(x), np.nan); a = 2.0 / (n + 1); s = np.nan
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        s = x[i] if np.isnan(s) else a * x[i] + (1 - a) * s
        out[i] = s
    return out


@njit(cache=True)
def atr(h, l, c, n=14):
    tr = np.full(len(c), np.nan)
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.full(len(c), np.nan); s = np.nan
    for i in range(len(c)):
        if np.isnan(tr[i]):
            continue
        s = tr[i] if np.isnan(s) else (s * (n - 1) + tr[i]) / n
        out[i] = s
    return out


@njit(cache=True)
def sma(x, n):
    out = np.full(len(x), np.nan); s = 0.0; k = 0
    for i in range(len(x)):
        s += x[i]; k += 1
        if k > n:
            s -= x[i - n]; k -= 1
        if k == n:
            out[i] = s / n
    return out


@njit(cache=True)
def rolling_max(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.max(x[i - n + 1:i + 1])
    return out


@njit(cache=True)
def rolling_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.min(x[i - n + 1:i + 1])
    return out


@njit(cache=True)
def rsi(c, n=14):
    out = np.full(len(c), np.nan); ag = 0.0; al = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        g = d if d > 0 else 0.0; lo = -d if d < 0 else 0.0
        if i <= n:
            ag += g / n; al += lo / n
            if i == n:
                out[i] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + lo) / n
            out[i] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    return out


@njit(cache=True)
def stdev(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.std(x[i - n + 1:i + 1])
    return out


# ------------------------------------------------------------------ estrutura de mercado (pivôs confirmados)
@njit(cache=True)
def pivots(h, l, k):
    """Para cada barra t, os 2 últimos topos e fundos CONFIRMADOS até t (preço e índice).
    Um topo em i é confirmado em i+k se h[i] for o máximo de h[i-k..i+k]."""
    n = len(h)
    sh1 = np.full(n, np.nan); sh2 = np.full(n, np.nan); shi1 = np.full(n, -1); shi2 = np.full(n, -1)
    sl1 = np.full(n, np.nan); sl2 = np.full(n, np.nan); sli1 = np.full(n, -1); sli2 = np.full(n, -1)
    a1 = np.nan; a2 = np.nan; ai1 = -1; ai2 = -1; b1 = np.nan; b2 = np.nan; bi1 = -1; bi2 = -1
    for t in range(n):
        i = t - k
        if i >= k:
            if h[i] == np.max(h[i - k:i + k + 1]) and not np.isnan(h[i]):
                a2 = a1; ai2 = ai1; a1 = h[i]; ai1 = i
            if l[i] == np.min(l[i - k:i + k + 1]) and not np.isnan(l[i]):
                b2 = b1; bi2 = bi1; b1 = l[i]; bi1 = i
        sh1[t] = a1; sh2[t] = a2; shi1[t] = ai1; shi2[t] = ai2
        sl1[t] = b1; sl2[t] = b2; sli1[t] = bi1; sli2[t] = bi2
    return sh1, sh2, shi1, shi2, sl1, sl2, sli1, sli2


@njit(cache=True)
def detect_all(o, h, l, c, v, k):
    """Roda todos os detectores para um ativo/timeframe. Retorna matriz de sinais (P×T) e de stops (P×T)."""
    n = len(c)
    P = 18
    S = np.zeros((P, n), np.bool_)
    ST = np.full((P, n), np.nan)
    A = atr(h, l, c, 14)
    e20 = ema(c, 20); e50 = ema(c, 50); e200 = ema(c, 200)
    vavg = sma(v, 20)
    r14 = rsi(c, 14)
    sh1, sh2, shi1, shi2, sl1, sl2, sli1, sli2 = pivots(h, l, k)
    hh20 = rolling_max(h, 20); ll20 = rolling_min(l, 20); hh55 = rolling_max(h, 55)
    m20 = sma(c, 20); sd20 = stdev(c, 20)
    # Ichimoku
    tenkan = (rolling_max(h, 9) + rolling_min(l, 9)) / 2
    kijun = (rolling_max(h, 26) + rolling_min(l, 26)) / 2
    spanA_raw = (tenkan + kijun) / 2
    spanB_raw = (rolling_max(h, 52) + rolling_min(l, 52)) / 2
    # contração (VCP): amplitude de 20 barras relativa ao preço, comparada à sua própria história (250 barras)
    rng20 = (hh20 - ll20) / c
    # FVG/OB: zonas ativas
    fvg_top = np.nan; fvg_bot = np.nan; fvg_age = 10 ** 9
    ob_top = np.nan; ob_bot = np.nan; ob_age = 10 ** 9
    sq_count = 0
    bear_run = 0
    hao = np.nan; hac = np.nan
    st_dir = 1; st_up = np.nan; st_dn = np.nan
    for t in range(260, n):
        if np.isnan(c[t]) or np.isnan(A[t]) or A[t] <= 0:
            continue
        at = A[t]
        uptrend = c[t] > e50[t] and e50[t] > e200[t]
        # --- 0 BOS de continuação (HH + HL) ---
        if not np.isnan(sh2[t]) and not np.isnan(sl2[t]):
            hh = sh1[t] > sh2[t]; hl = sl1[t] > sl2[t]
            lh = sh1[t] < sh2[t]; ll = sl1[t] < sl2[t]
            cross = c[t] > sh1[t] and c[t - 1] <= sh1[t]
            if cross and hh and hl:
                S[0, t] = True; ST[0, t] = sl1[t]
            # --- 1 CHoCH (mudança de caráter: estrutura de baixa rompida para cima) ---
            if cross and lh and ll:
                S[1, t] = True; ST[1, t] = sl1[t]
        # --- 2 Varredura de liquidez / spring (Wyckoff) ---
        if not np.isnan(sl1[t]):
            rngt = h[t] - l[t]
            if l[t] < sl1[t] and c[t] > sl1[t] and rngt > 0 and (min(o[t], c[t]) - l[t]) / rngt >= 0.5:
                S[2, t] = True; ST[2, t] = l[t]
        # --- 3 FVG de alta: cria zona; sinal no 1º reteste com tendência de alta ---
        if l[t] > h[t - 2] and (c[t - 1] - o[t - 1]) > 1.0 * at:
            fvg_top = l[t]; fvg_bot = h[t - 2]; fvg_age = 0
        else:
            fvg_age += 1
        if fvg_age > 0 and fvg_age <= 30 and not np.isnan(fvg_top):
            if l[t] <= fvg_top and c[t] > fvg_bot and c[t] > e50[t]:
                S[3, t] = True; ST[3, t] = fvg_bot - 0.5 * at
                fvg_age = 10 ** 9
            elif c[t] < fvg_bot:
                fvg_age = 10 ** 9
        # --- 4 Order block: no BOS de alta, último candle de baixa antes do impulso; sinal no reteste ---
        if S[0, t] or S[1, t]:
            for j in range(t - 1, max(t - 12, 1), -1):
                if c[j] < o[j]:
                    ob_top = h[j]; ob_bot = l[j]; ob_age = 0
                    break
        else:
            ob_age += 1
        if ob_age > 0 and ob_age <= 40 and not np.isnan(ob_top):
            if l[t] <= ob_top and c[t] > ob_bot:
                S[4, t] = True; ST[4, t] = ob_bot - 0.25 * at
                ob_age = 10 ** 9
            elif c[t] < ob_bot:
                ob_age = 10 ** 9
        # --- 5 Fundo duplo: 2 fundos parecidos (±0,5 ATR), separados >= 5 barras; rompe a linha do pescoço ---
        if not np.isnan(sl2[t]) and sli1[t] - sli2[t] >= 5 and abs(sl1[t] - sl2[t]) <= 0.5 * at:
            neck = np.max(h[sli2[t]:sli1[t] + 1])
            if c[t] > neck and c[t - 1] <= neck and t - sli1[t] <= 30:
                S[5, t] = True; ST[5, t] = min(sl1[t], sl2[t])
        # --- 6 Triângulo ascendente: topos planos (±0,5 ATR) + fundos ascendentes; rompimento ---
        if not np.isnan(sh2[t]) and not np.isnan(sl2[t]):
            if abs(sh1[t] - sh2[t]) <= 0.5 * at and sl1[t] > sl2[t]:
                top = max(sh1[t], sh2[t])
                if c[t] > top and c[t - 1] <= top:
                    S[6, t] = True; ST[6, t] = sl1[t]
        # --- 7 Bandeira de alta: mastro >= 4 ATR em <= 10 barras, consolidação 5-20 barras estreita, rompe c/ volume ---
        for cons in range(5, 21):
            p = t - cons  # fim do mastro
            if p - 10 < 0:
                break
            pole = c[p] - np.min(l[p - 10:p + 1])
            if pole < 4 * at:
                continue
            ch = np.max(h[p + 1:t]); cl = np.min(l[p + 1:t])
            if (ch - cl) <= 0.5 * pole and cl >= c[p] - 0.5 * pole and c[t] > ch and c[t - 1] <= ch and v[t] > 1.2 * vavg[t]:
                S[7, t] = True; ST[7, t] = cl
                break
        # --- 8 VCP / contração (Minervini): amplitude de 20 barras no 20º percentil do último ano, tendência estágio 2 ---
        hist = rng20[t - 250:t]
        q = np.nanpercentile(hist, 20)
        if rng20[t - 1] <= q and uptrend and c[t] > hh20[t - 1] and v[t] > 1.5 * vavg[t]:
            S[8, t] = True; ST[8, t] = ll20[t - 1]
        # --- 9 Squeeze TTM: Bollinger(20,2) dentro de Keltner(20,1.5) >= 6 barras, depois dispara para cima ---
        inside = (m20[t] + 2 * sd20[t]) < (e20[t] + 1.5 * at) and (m20[t] - 2 * sd20[t]) > (e20[t] - 1.5 * at)
        if inside:
            sq_count += 1
        else:
            if sq_count >= 6 and c[t] > m20[t] + 2 * sd20[t] and c[t] > c[t - 1]:
                S[9, t] = True; ST[9, t] = c[t] - 2 * at
            sq_count = 0
        # --- 10 Rompimento Donchian 55 com volume (Turtle + confirmação) ---
        if c[t] > hh55[t - 1] and v[t] > 1.5 * vavg[t]:
            S[10, t] = True; ST[10, t] = c[t] - 2 * at
        # --- 11 Ichimoku: fecha acima da nuvem (projetada 26 barras atrás), tenkan>kijun, chikou>preço de 26 barras, nuvem futura de alta ---
        cloud_top = max(spanA_raw[t - 26], spanB_raw[t - 26])
        prev_top = max(spanA_raw[t - 27], spanB_raw[t - 27])
        if c[t] > cloud_top and c[t - 1] <= prev_top and tenkan[t] > kijun[t] and c[t] > c[t - 26] and spanA_raw[t] > spanB_raw[t]:
            S[11, t] = True; ST[11, t] = min(kijun[t], cloud_top)
        # --- 12 Divergência de alta no RSI: novo fundo mais baixo com RSI mais alto, RSI anterior < 35 ---
        if sli1[t] > 0 and sli2[t] > 0 and t - sli1[t] == k:
            if sl1[t] < sl2[t] and r14[sli1[t]] > r14[sli2[t]] and r14[sli2[t]] < 35:
                S[12, t] = True; ST[12, t] = sl1[t]
        # --- 13 Engolfo de alta em suporte (fundo anterior ou EMA200) ---
        if c[t] > o[t] and c[t - 1] < o[t - 1] and c[t] >= o[t - 1] and o[t] <= c[t - 1]:
            near = (not np.isnan(sl1[t]) and abs(l[t] - sl1[t]) <= 0.5 * at) or abs(l[t] - e200[t]) <= 0.5 * at
            if near:
                S[13, t] = True; ST[13, t] = l[t] - 0.25 * at
        # --- 14 Pullback na EMA20 em tendência (EMA20>EMA50>EMA200), candle de rejeição ---
        if e20[t] > e50[t] and e50[t] > e200[t] and l[t] <= e20[t] and c[t] > e20[t] and c[t] > o[t]:
            S[14, t] = True; ST[14, t] = min(l[t], e50[t]) - 0.5 * at
        # --- 15 Supertrend(10,3) virando para alta ---
        hl2 = (h[t] + l[t]) / 2
        up = hl2 - 3 * at; dn = hl2 + 3 * at
        st_up = up if np.isnan(st_up) or c[t - 1] < st_up else max(up, st_up)
        st_dn = dn if np.isnan(st_dn) or c[t - 1] > st_dn else min(dn, st_dn)
        prev = st_dir
        if c[t] > st_dn:
            st_dir = 1
        elif c[t] < st_up:
            st_dir = -1
        if st_dir == 1 and prev == -1:
            S[15, t] = True; ST[15, t] = st_up
        # --- 16 Heikin-Ashi: candle HA forte (sem pavio inferior) após >= 3 HA de baixa ---
        nc = (o[t] + h[t] + l[t] + c[t]) / 4
        no = (o[t - 1] + c[t - 1]) / 2 if np.isnan(hao) else (hao + hac) / 2
        if nc < no:
            bear_run += 1
        else:
            if bear_run >= 3 and l[t] >= min(no, nc):  # HA de alta sem pavio inferior
                S[16, t] = True; ST[16, t] = l[t] - 0.5 * at
            bear_run = 0
        hao = no; hac = nc
        # --- 17 Confluência SMC: varredura de liquidez + CHoCH em até 10 barras (Wyckoff spring + mudança de caráter) ---
        if S[1, t]:
            for j in range(t - 1, max(t - 11, 0), -1):
                if S[2, j]:
                    S[17, t] = True; ST[17, t] = ST[2, j]
                    break
    return S, ST


NAMES = ["BOS_continuacao", "CHoCH_reversao", "Varredura_liquidez_spring", "FVG_reteste", "OrderBlock_reteste",
         "Fundo_duplo", "Triangulo_ascendente", "Bandeira_alta", "VCP_Minervini", "Squeeze_TTM", "Donchian55_volume",
         "Ichimoku_rompe_nuvem", "Divergencia_RSI", "Engolfo_em_suporte", "Pullback_EMA20", "Supertrend_virada",
         "HeikinAshi_reversao", "SMC_varredura+CHoCH"]


@njit(cache=True)
def manage(o, h, l, c, A, t0, stop0, trail_atr, max_bars, min_r, max_r):
    """Gestão padronizada de uma operação comprada que entra na abertura de t0+1.
    Stop inicial = nível técnico, limitado a [min_r, max_r] ATRs da entrada; depois stop móvel (chandelier)
    = máxima de fechamento - trail_atr*ATR; sai no stop (ou abertura, se abrir abaixo) ou após max_bars."""
    n = len(c)
    e = t0 + 1
    if e >= n or np.isnan(o[e]):
        return np.nan, 0
    entry = o[e]
    at = A[t0]
    risk = entry - stop0
    if np.isnan(risk) or risk < min_r * at:
        risk = min_r * at
    if risk > max_r * at:
        risk = max_r * at
    stop = entry - risk
    hc = entry
    for i in range(e, min(n, e + max_bars)):
        if np.isnan(l[i]):
            continue
        if l[i] <= stop:
            px = min(o[i], stop)
            return px / entry - 1.0, i - e + 1
        hc = max(hc, c[i])
        if not np.isnan(A[i]):
            stop = max(stop, hc - trail_atr * A[i])
    last = min(n, e + max_bars) - 1
    return c[last] / entry - 1.0, last - e + 1
