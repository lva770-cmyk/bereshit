"""Project 50 (zone RO2): rule-based second discharge in the Romanian intraday market (paper trading only).

The day-ahead plan commits ONE discharge (engine RO2: 1 full cycle). On the delivery day the battery may sell a
second time in the continuous intraday market (OPCOM), with standing limit orders:
  * SELL at >= SELL_AT EUR/MWh (hour fills if that hour's highest trade reached the limit; paid the limit price),
  * after a sale, BUY BACK only at <= BUY_AT EUR/MWh,
  * unless it is the last window to still deliver yesterday's day-ahead commitment - then buy at any price
    (paid the hour's volume-weighted average, ROPEX_ID).
Energy sold early is energy "borrowed" from the day-ahead plan; it must be back in the battery before the plan
needs it, and the day ends at the plan's state of charge. Volumes are capped at SHARE of the hour's traded volume
(except the forced buy). Everything is evaluated hour by hour, in time order, using only hours whose trading is over.
Prices: OPCOM continuous market report (min / max / ROPEX_ID per hour, RON -> EUR at the ECB rate)."""
import re, html, datetime as dt, urllib.request, urllib.parse, http.cookiejar
import numpy as np

SELL_AT, BUY_AT, SHARE = 310.0, 150.0, 0.2
URL = "https://www.opcom.ro/rapoarte-pi-raport-cuplare-pi/ro"

def _num(s):
    s = s.strip()
    if not s or s == "-": return None
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return None

def fetch_opcom(day):
    """{delivery_date: [(label, min, max, last, ropex, pmp1, vol_buy, vol_sell)]} for `day` (and the day before)."""
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (bereshit research)"), ("Accept-Language", "ro,en")]
    h = op.open(URL, timeout=60).read().decode("utf8", "replace")
    tok = re.search(r'name="_token" value="([^"]+)"', h).group(1)
    data = {"_token": tok, "ziua": (dt.date.fromisoformat(day) + dt.timedelta(days=1)).strftime("%d/%m/%Y"), "buton": "Refresh",
            "action": "trading_for", "limba": "ro", "tip": "60"}
    h = op.open(urllib.request.Request(URL, urllib.parse.urlencode(data).encode()), timeout=90).read().decode("utf8", "replace")
    days = [dt.datetime.strptime(x, "%d.%m.%Y").date().isoformat() for x in re.findall(r"Ziua de livrare (\d\d\.\d\d\.\d{4})", h)]
    out = {}
    tabs = []
    for t in re.findall(r"<table.*?</table>", h, re.S):
        rows = []
        for r in re.findall(r"<tr.*?</tr>", t, re.S):
            c = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[dh][^>]*>.*?</t[dh]>", r, re.S)]
            if c: rows.append(c)
        if len(rows) > 3 and any("ROPEX_ID_H" in x for x in rows[1]): tabs.append(rows)
    for d, rows in zip(days, tabs):
        out[d] = [(r[0], *[_num(x) for x in r[1:8]]) for r in rows[3:] if r and re.match(r"^\d", r[0]) and len(r) >= 8]
    return out

def hourly(rows, rate):
    """24 hours of (min, max, ropex, vol_buy, vol_sell) in EUR/MWh and MWh. The repeated autumn hour is dropped."""
    st = [None] * 24
    for lab, mn, mx, last, rop, pmp1, vb, vs in rows:
        if "*" in lab: continue
        h = int(lab[:2])
        if 0 <= h < 24:
            f = lambda v: None if v is None else v / rate
            st[h] = (f(mn), f(mx), f(rop), vb or 0.0, vs or 0.0)
    return st

def run_day(net, st, P=50.0, E=89.5, rte=0.88, sell_at=SELL_AT, buy_at=BUY_AT, share=SHARE, hours_done=24, da=None):
    """net: 96 quarter-hour day-ahead positions (MW, + = sell). st: 24 hourly stats (or None).
    Returns trades per hour and the intraday P&L (on top of the day-ahead settlement)."""
    ec = ed = rte ** .5
    n = np.asarray(net, float).reshape(24, 4)
    nh = n.mean(axis=1)                                    # MW, hourly average of the plan
    e = 0.0; eda = np.zeros(24)                             # cell energy at the end of each hour under the plan
    for h in range(24):
        for q in n[h]: e += (-q * .25 * ec) if q < 0 else (-q * .25 / ed)
        eda[h] = max(e, 0.0)
    dah = None if da is None else np.asarray(da, float).reshape(24, 4).mean(axis=1)
    x = np.zeros(24); y = np.zeros(24)                     # MW sold / bought back in each hour
    B = 0.0; extra = 0.0; cap_extra = E * ed               # borrowed cell energy; at most one extra full discharge
    trades = []

    def can_repay(k0, b):
        for k in range(k0, 24):
            room = max(0.0, P + nh[k] - x[k])              # charging headroom left in hour k
            b = max(0.0, b - room * ec)
            if b > eda[k] + 1e-6: return False
        return b <= 1e-6

    for h in range(min(hours_done, 24)):
        s = st[h] if h < len(st) else None
        mn, mx, rop, vb, vs = s if s else (None, None, None, 0.0, 0.0)
        # 1) sell at >= sell_at (standing limit order filled if the hour traded that high)
        if mx is not None and mx >= sell_at and extra < cap_extra:
            hi = min(P - nh[h], share * vb, cap_extra - extra)
            lo_, up_ = 0.0, max(0.0, hi)
            for _ in range(30):                             # largest sale that can still be paid back in time
                m = (lo_ + up_) / 2; b = B + m / ed
                (lo_, up_) = (m, up_) if (b <= eda[h] + 1e-6 and can_repay(h + 1, b)) else (lo_, m)
            v = lo_ if lo_ > 0.05 else 0.0
            if v:
                x[h] = v; B += v / ed; extra += v
                trades.append({"h": h, "side": "sell", "mw": round(v, 1), "px": sell_at, "kind": "limit"})
                continue
        if B <= 1e-6: continue
        room = max(0.0, P + nh[h] - x[h])
        # 2) buy back at <= buy_at
        if mn is not None and mn <= buy_at:
            v = min(room, share * vs, B / ec)
            if v > 0.05:
                y[h] = v; B = max(0.0, B - v * ec)
                trades.append({"h": h, "side": "buy", "mw": round(v, 1), "px": buy_at, "kind": "limit"}); room -= v
        # 3) last window: buy whatever is needed at any price
        if B > 1e-6 and not (B <= eda[h] + 1e-6 and can_repay(h + 1, B)):
            lo_, up_ = 0.0, room
            for _ in range(30):
                m = (lo_ + up_) / 2; b = max(0.0, B - m * ec)
                (lo_, up_) = (lo_, m) if (b <= eda[h] + 1e-6 and can_repay(h + 1, b)) else (m, up_)
            v = up_
            if v > 0.05:
                px = rop if rop is not None else (dah[h] if dah is not None else buy_at)
                y[h] += v; B = max(0.0, B - v * ec)
                trades.append({"h": h, "side": "buy", "mw": round(v, 1), "px": round(px, 2), "kind": "deadline"})
    pnl = sum((t["mw"] * t["px"]) * (1 if t["side"] == "sell" else -1) for t in trades)
    return {"trades": trades, "pnl": round(pnl, 2), "sold_mwh": round(float(x.sum()), 1), "bought_mwh": round(float(y.sum()), 1),
            "open_mwh": round(B / ec, 2)}
