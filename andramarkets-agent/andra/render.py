def build_exhibits(mf, tmp: str) -> dict[str, str]:
    charts.house_style()
    ex: dict[str, str] = {}
    p = lambda n: os.path.join(tmp, f"{n}.png")  # noqa: E731

    picks = [("spx", "S&P 500"), ("sx5e", "EURO STOXX 50"),
             ("nky", "Nikkei 225"), ("hsi", "Hang Seng"), ("ibov", "Bovespa")]
    series, x = {}, None
    for k, label in picks:
        if k in mf.px.columns:
            s = mf.series(k, 60)
            if len(s) > 10:
                series[label] = s.values
                x = [d.strftime("%d %b") for d in s.index]
    if series:
        ex["regions"] = _b64(charts.line_rebased(series, x, p("regions"), size=(10.6, 1.36), base_label=None))

    sec = mf.block("sectors")
    if not sec.empty:
        names, vals = sec["name"].tolist(), sec["chg"].tolist()
        ex["sectors"] = _b64(charts.bars_ranked(names, vals, p("sec"), size=(3.15, 2.6)))
        ex["sectors_sq"] = _b64(charts.bars_ranked(names, vals, p("sec_sq"), size=(7.6, 5.2)))
        ex["sectors_tt"] = _b64(charts.bars_ranked(names, vals, p("sec_tt"), size=(7.2, 6.4)))

    b = breadth(mf)
    ex["breadth"] = _b64(charts.breadth_bar(b["advancers"], b["decliners"],
                                            b["unchanged"], p("breadth")))

    c = mf.block("curve")
    if not c.empty:
        tenors = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
        today = c["last"].tolist()
        prior = [t - (w or 0) / 100 for t, w in zip(today, c["w1"].fillna(0).tolist())]
        tenors = tenors[:len(today)]
        ex["curve"] = _b64(charts.yield_curve(tenors, today, prior, p("curve"), size=(3.2, 2.9)))
        ex["curve_sq"] = _b64(charts.yield_curve(tenors, today, prior, p("curve_sq"), size=(7.6, 4.3)))

    cr = mf.block("credit")
    if not cr.empty:
        start = [float(l) / (1 + (w or 0) / 100) for l, w in zip(cr["last"], cr["w1"].fillna(0))]
        ex["credit"] = _b64(charts.dumbbell(cr["name"].tolist(), start,
                                            cr["last"].tolist(), p("credit"),
                                            size=(3.15, 4.6), unit="%"))

    fx = mf.block("fx")
    if not fx.empty:
        ex["fx"] = _b64(charts.bars_ranked(fx["name"].tolist(), fx["chg"].tolist(),
                                           p("fx"), size=(3.15, 3.3)))
    cm = mf.block("commodities")
    if not cm.empty:
        ex["commodities"] = _b64(charts.bars_ranked(cm["name"].tolist(), cm["chg"].tolist(),
                                                    p("cmd"), size=(3.15, 3.6)))
    if "vix" in mf.px.columns:
        s = mf.series("vix", 120)
        lab = [d.strftime("%d %b") for d in s.index]
        ex["vix"] = _b64(charts.area_vol(lab, s.values, p("vix")))
        ex["vix_sq"] = _b64(charts.area_vol(lab, s.values, p("vix_sq"), size=(7.6, 4.2)))

    if {"real10y", "be10y"} <= set(mf.px.columns):
        a, bb = mf.series("real10y", 120), mf.series("be10y", 120)
        if len(a) > 20 and len(bb) > 20:
            ex["real"] = _b64(charts.dual_axis([d.strftime("%d %b") for d in a.index],
                                               ("10-year real yield", a.values),
                                               ("10-year breakeven", bb.values),
                                               p("real"), size=(3.15, 2.2)))

    corr = cross_correlation(mf, ["spx", "ndx", "ust10y", "dxy", "gold",
                                  "wti", "btc", "hyg"], 60)
    if not corr.empty:
        keep = [k for k in corr.columns if k in mf.snap.index]
        corr = corr.loc[keep, keep]
    if not corr.empty:
        labels = [str(mf.snap.at[k, "name"]) for k in corr.columns]
        ex["correlation"] = _b64(charts.corr_matrix(labels, corr.values, p("corr"),
                                                    size=(3.15, 1.95)))

    # --- social art: one continuous line per carousel, plus the bare curve ---
    if "spx" in mf.px.columns:
        path = mf.series("spx", 260).values
        for tag, w, h in (("tt", 7 * 1080, 600), ("li", 8 * 1200, 620)):
            ex[f"ribbon_{tag}_dark"] = _b64(charts.ribbon(
                path, p(f"rb_{tag}_d"), w, h, colour=charts.INK))
            ex[f"ribbon_{tag}_light"] = _b64(charts.ribbon(
                path, p(f"rb_{tag}_l"), w, h, colour="#FFFFFF"))

    if not c.empty:
        ex["curve_bare"] = _b64(charts.curve_bare(tenors, today, prior,
                                                  p("cb_tt"), 1080, 360,
                                                  colour="#FFFFFF", ghost="#6E6E6E"))
        ex["curve_bare_li"] = _b64(charts.curve_bare(tenors, today, prior,
                                                     p("cb_li"), 1200, 300,
                                                     colour="#FFFFFF", ghost="#6E6E6E"))

    rows, cols, data = horizon_matrix(mf, ["spx", "ndx", "sx5e", "nky",
                                           "ust10y", "gold", "wti", "btc"])
    if rows:
        ex["heatmap"] = _b64(charts.heat_matrix(rows, cols, data, p("heat"), size=(7.6, 1.14)))
    return ex
