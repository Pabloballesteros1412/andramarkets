"""Exhibit engine.

House rules: no blue in any graphical element, and colour is reserved for
data. Multi-series charts run on a greyscale ramp anchored by black; gains
print deep green and losses deep red. Everything renders at 300 dpi on white.
"""
from __future__ import annotations

import os
from typing import Iterable, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np

# ----------------------------------------------------------------- tokens ---
INK, GRAPHITE, SLATE, MIST = "#0E0E0E", "#2B2B2B", "#767676", "#A6A6A6"
RULE, PAPER, PANEL, ACCENT = "#D2D2D2", "#FFFFFF", "#F5F5F5", "#12684A"
UP, DOWN, FLAT = "#12684A", "#9C2A22", "#767676"

# Serie cualitativa (5 lineas maximo por exhibit). Cero azul.
QUAL = [INK, "#8A8A8A", "#12684A", "#B8B8B8", "#5A5A5A"]

# Rampa divergente oxblood a hueso a verde bosque (sustituye a RdBu)
DIVERGING = [
    "#8E2018", "#AE5148", "#CB8880", "#E5BFBA", "#FFFFFF",
    "#C6D8CD", "#8FB6A2", "#4E8E70", "#12684A",
]

_SANS = ["Inter", "Neue Haas Grotesk Display", "Helvetica Neue",
         "TeX Gyre Heros", "Liberation Sans", "DejaVu Sans"]


def house_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": _SANS,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "axes.edgecolor": INK,
        "axes.linewidth": 0.7,
        "axes.labelcolor": SLATE,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": SLATE, "ytick.color": SLATE,
        "xtick.labelsize": 6.6, "ytick.labelsize": 6.6,
        "xtick.major.size": 2.2, "ytick.major.size": 0,
        "xtick.major.width": 0.6,
        "grid.color": "#EBEBEB", "grid.linewidth": 0.5,
        "legend.frameon": False, "legend.fontsize": 6.4,
        "figure.dpi": 300, "savefig.dpi": 300,
        "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    })


def _finish(ax, ylab: str | None = None) -> None:
    ax.yaxis.grid(True); ax.xaxis.grid(False); ax.set_axisbelow(True)
    ax.tick_params(axis="y", pad=1.5)
    if ylab:
        ax.set_ylabel(ylab, fontsize=6.2, labelpad=3, color=MIST)


def _save(fig, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path); plt.close(fig)
    return path


# ============================================================== EXHIBITS ====
def line_rebased(series: dict[str, Sequence[float]], x: Sequence,
                 path: str, size=(6.6, 2.5), base_label="Rebased to 100") -> str:
    """Comportamiento relativo rebasado a 100 (indices, regiones, factores)."""
    fig, ax = plt.subplots(figsize=size)
    finales = []
    for i, (name, y) in enumerate(series.items()):
        y = np.asarray(y, dtype=float)
        y = 100.0 * y / y[0]
        ax.plot(x, y, color=QUAL[i % len(QUAL)], lw=1.15, zorder=3, label=name)
        finales.append([y[-1], name, QUAL[i % len(QUAL)]])

    finales.sort(key=lambda r: r[0])
    vals = [f[0] for f in finales]
    minimo = (max(vals) - min(vals) or 1) * 0.085
    for j in range(1, len(finales)):
        if finales[j][0] - finales[j - 1][0] < minimo:
            finales[j][0] = finales[j - 1][0] + minimo
    for (ypos, name, col), real in zip(finales, sorted(vals)):
        ax.annotate(f"{name}  {real:.1f}", xy=(len(x) - 1, ypos),
                    xytext=(5, 0), textcoords="offset points",
                    fontsize=6.0, color=col, va="center", fontweight="bold")
    ax.axhline(100, color=MIST, lw=0.5, ls=(0, (2, 2)), zorder=1)
    ax.set_xlim(0, len(x) - 1 + max(6, len(x) * 0.22))
    ax.set_xticks(range(0, len(x), max(1, len(x) // 6)))
    ax.set_xticklabels([str(x[i]) for i in range(0, len(x), max(1, len(x) // 6))])
    _finish(ax, base_label)
    return _save(fig, path)


def bars_ranked(labels: Sequence[str], values: Sequence[float], path: str,
                size=(3.15, 3.0), unit="%", horizontal=True) -> str:
    """Ranking ordenado (sectores GICS, divisas, materias primas)."""
    order = np.argsort(values)
    lab = [labels[i] for i in order]
    val = [values[i] for i in order]
    col = [UP if v > 0 else (DOWN if v < 0 else FLAT) for v in val]

    fig, ax = plt.subplots(figsize=size)
    if horizontal:
        ax.barh(lab, val, color=col, height=0.66, zorder=3)
        ax.axvline(0, color=INK, lw=0.8, zorder=4)
        pad = (max(map(abs, val)) or 1) * 0.06
        for y, v in enumerate(val):
            ax.text(v + (pad if v >= 0 else -pad), y, f"{v:+.2f}{unit}",
                    va="center", ha="left" if v >= 0 else "right",
                    fontsize=6.1, color=INK, fontweight="bold")
        ax.set_xlim(min(0, min(val)) * 1.42 - pad, max(0, max(val)) * 1.42 + pad)
        ax.set_xticks([]); ax.xaxis.grid(False); ax.yaxis.grid(False)
        for s in ("bottom", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis="y", length=0, labelsize=6.4)
    else:
        ax.bar(lab, val, color=col, width=0.68, zorder=3)
        ax.axhline(0, color=INK, lw=0.8)
        _finish(ax, unit)
    return _save(fig, path)


def yield_curve(tenors: Sequence[str], today: Sequence[float],
                prior: Sequence[float], path: str,
                size=(3.2, 2.35), prior_label="One week ago") -> str:
    """Curva soberana: nivel de hoy contra referencia, con delta en pb."""
    x = np.arange(len(tenors))
    fig, ax = plt.subplots(figsize=size)
    ax.plot(x, prior, color=MIST, lw=1.0, ls=(0, (3, 2)), zorder=2, label=prior_label)
    ax.plot(x, today, color=INK, lw=1.5, zorder=3, label='Latest close')
    ax.scatter(x, today, s=9, color=INK, zorder=4)
    for xi, (t, p) in enumerate(zip(today, prior)):
        d = (t - p) * 100
        ax.annotate(f"{d:+.0f}" if abs(d) >= 0.5 else "0", xy=(xi, t), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=5.6, fontweight="bold",
                    color=DOWN if d > 0 else (UP if d < 0 else MIST))
    ax.set_xticks(x); ax.set_xticklabels(tenors)
    ax.set_ylim(min(min(today), min(prior)) - 0.12, max(max(today), max(prior)) + 0.20)
    ax.legend(loc="lower right", ncol=1)
    _finish(ax, "%  ·  etiqueta = delta pb")
    return _save(fig, path)


def area_vol(x: Sequence, y: Sequence[float], path: str, size=(3.2, 2.0),
             ylab="Indice") -> str:
    """Serie de volatilidad con relleno y banda de media movil."""
    y = np.asarray(y, dtype=float)
    fig, ax = plt.subplots(figsize=size)
    ax.fill_between(range(len(y)), y.min() * 0.94, y, color=PANEL, zorder=2)
    ax.plot(range(len(y)), y, color=INK, lw=1.2, zorder=4)
    if len(y) >= 20:
        ma = np.convolve(y, np.ones(20) / 20, mode="valid")
        ax.plot(range(19, len(y)), ma, color=MIST, lw=1.0,
                ls=(0, (3, 2)), zorder=3, label="20-session average")
        ax.legend(loc="upper left")
    ax.scatter([len(y) - 1], [y[-1]], s=13, color=INK, zorder=5)
    ax.annotate(f"{y[-1]:.2f}", xy=(len(y) - 1, y[-1]), xytext=(-2, 7),
                textcoords="offset points", ha="right", fontsize=6.6,
                fontweight="bold", color=INK)
    step = max(1, len(x) // 5)
    ax.set_xticks(range(0, len(x), step))
    ax.set_xticklabels([str(x[i]) for i in range(0, len(x), step)])
    ax.set_ylim(y.min() * 0.94, y.max() * 1.10)
    _finish(ax, ylab)
    return _save(fig, path)


def heat_matrix(rows: Sequence[str], cols: Sequence[str],
                data: Iterable[Iterable[float]], path: str,
                size=(6.6, 1.9), unit="%") -> str:
    """Matriz de rendimientos (activo x horizonte) en rampa oxblood a verde."""
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    m = np.asarray(list(data), dtype=float)
    cmap = LinearSegmentedColormap.from_list("andra_div", DIVERGING)
    lim = max(0.35, float(np.nanpercentile(np.abs(m), 92)))
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)

    fig, ax = plt.subplots(figsize=size)
    ax.imshow(m, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, fontsize=6.2)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels(rows, fontsize=6.2)
    ax.tick_params(length=0)
    ax.xaxis.set_ticks_position("top")
    for s in ax.spines.values():
        s.set_visible(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m[i, j]
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=5.9,
                    fontweight="bold",
                    color=PAPER if abs(v) > lim * 0.62 else INK)
    ax.set_xticks(np.arange(-.5, len(cols), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(rows), 1), minor=True)
    ax.grid(which="minor", color=PAPER, lw=1.1)
    ax.tick_params(which="minor", length=0)
    return _save(fig, path)


def dual_axis(x: Sequence, izq: tuple[str, Sequence[float]],
              der: tuple[str, Sequence[float]], path: str,
              size=(3.15, 2.05)) -> str:
    """Dos series en ejes independientes (tipo real frente a implicita)."""
    fig, ax = plt.subplots(figsize=size)
    ax2 = ax.twinx()
    ax.plot(range(len(izq[1])), izq[1], color=INK, lw=1.25, zorder=3)
    ax2.plot(range(len(der[1])), der[1], color=ACCENT, lw=1.15,
             ls=(0, (3, 2)), zorder=3)
    ax.set_ylabel(izq[0], fontsize=5.9, color=INK, labelpad=3)
    ax2.set_ylabel(der[0], fontsize=5.9, color=ACCENT, labelpad=4, rotation=270,
                   va="bottom")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color(RULE)
    ax2.tick_params(colors=ACCENT, labelsize=6.4)
    step = max(1, len(x) // 5)
    ax.set_xticks(range(0, len(x), step))
    ax.set_xticklabels([str(x[i]) for i in range(0, len(x), step)])
    _finish(ax)
    return _save(fig, path)


def corr_matrix(labels: Sequence[str], m, path: str, size=(3.15, 2.75)) -> str:
    """Correlacion de rendimientos diarios. Triangulo inferior, sin azul."""
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    m = np.asarray(m, dtype=float)
    mask = np.triu(np.ones_like(m, dtype=bool), k=1)
    m = np.where(mask, np.nan, m)
    cmap = LinearSegmentedColormap.from_list("andra_corr", DIVERGING)
    cmap.set_bad("#FFFFFF")

    fig, ax = plt.subplots(figsize=size)
    ax.imshow(m, cmap=cmap, norm=TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1),
              aspect="auto")
    corto = [l if len(l) <= 12 else l[:11] + "." for l in labels]
    ax.xaxis.set_ticks_position("top")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(corto, fontsize=5.2, rotation=45, ha="left")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(corto, fontsize=5.5)
    ax.tick_params(length=0)
    for s_ in ax.spines.values():
        s_.set_visible(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if np.isnan(m[i, j]):
                continue
            ax.text(j, i, f"{m[i, j]:.2f}".replace("0.", "."), ha="center",
                    va="center", fontsize=5.2, fontweight="bold",
                    color=PAPER if abs(m[i, j]) > 0.62 else INK)
    ax.set_xticks(np.arange(-.5, len(labels), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(labels), 1), minor=True)
    ax.grid(which="minor", color=PAPER, lw=1.0)
    ax.tick_params(which="minor", length=0)
    return _save(fig, path)


def breadth_bar(adv: int, dec: int, unch: int, path: str, size=(3.15, 0.62)) -> str:
    """Amplitud del mercado: avances / retrocesos / sin cambio."""
    total = max(adv + dec + unch, 1)
    fig, ax = plt.subplots(figsize=size)
    left = 0.0
    for v, c, t in ((adv, UP, "Advancing"), (unch, MIST, "Unchanged"), (dec, DOWN, "Declining")):
        w = 100 * v / total
        ax.barh([0], [w], left=[left], color=c, height=0.85)
        if w > 8:
            ax.text(left + w / 2, 0, f"{t}  {v}", ha="center", va="center",
                    fontsize=6.0, color=PAPER, fontweight="bold")
        left += w
    ax.set_xlim(0, 100); ax.axis("off")
    return _save(fig, path)


def dumbbell(labels: Sequence[str], start: Sequence[float], end: Sequence[float],
             path: str, size=(3.15, 2.6), unit="pb") -> str:
    """Comparativa nivel previo vs nivel actual (spreads de credito, primas)."""
    y = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=size)
    for i, (s, e) in enumerate(zip(start, end)):
        ax.plot([s, e], [i, i], color=RULE, lw=1.6, zorder=2)
        ax.scatter([s], [i], s=17, color=MIST, zorder=3)
        ax.scatter([e], [i], s=26, color=DOWN if e > s else UP, zorder=4)
        var = 100 * (e / s - 1) if unit == "%" and s else (e - s)
        etiqueta = (f"{e:,.2f} ({var:+.2f} %)" if unit == "%"
                    else f"{e:.0f} ({e - s:+.0f} {unit})")
        ax.text(max(s, e) + (max(end) - min(start) + 1) * 0.05, i,
                etiqueta, va="center", fontsize=5.8, color=INK,
                fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=6.4)
    ax.tick_params(length=0)
    ax.set_xlim(min(start + end) * 0.90, max(start + end) * 1.40)
    ax.spines["left"].set_visible(False)
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter("{x:.0f}"))
    ax.yaxis.grid(False); ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    return _save(fig, path)


# ============================================================ SOCIAL ART ====
# The carousels are held together by one continuous line. A single very wide
# ribbon is rendered once and each slide shows a different window of it, so the
# curve carries on when the reader swipes. Everything here is drawn edge to
# edge on a transparent ground: no axes, no frame, no legend.

def ribbon(values, path: str, width_px: int, height_px: int,
           colour: str = INK, fill: bool = True, lw: float = 3.2) -> str:
    """One wide continuous line, sized to exact pixels, transparent ground."""
    y = np.asarray(values, dtype=float)
    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    x = np.arange(len(y))
    if fill:
        ax.fill_between(x, y.min() - (np.ptp(y) or 1) * 0.55, y,
                        color=colour, alpha=0.07, lw=0)
    ax.plot(x, y, color=colour, lw=lw, solid_capstyle="round")
    ax.set_xlim(0, len(y) - 1)
    pad = (np.ptp(y) or 1) * 0.22
    ax.set_ylim(y.min() - pad, y.max() + pad)
    ax.axis("off")
    fig.patch.set_alpha(0)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(path, transparent=True, dpi=100, pad_inches=0)
    plt.close(fig)
    return path


def curve_bare(tenors, today, prior, path: str, width_px: int, height_px: int,
               colour: str = INK, ghost: str = "#8A8A8A") -> str:
    """The Treasury curve as a drawing rather than a chart."""
    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    ax = fig.add_axes([0.045, 0.24, 0.915, 0.70])
    x = np.arange(len(tenors))
    ax.plot(x, prior, color=ghost, lw=2.0, ls=(0, (4, 4)))
    ax.plot(x, today, color=colour, lw=3.4, solid_capstyle="round")
    ax.scatter(x, today, s=46, color=colour, zorder=4)
    for xi, t in zip(x, tenors):
        ax.annotate(t, xy=(xi, 0), xytext=(0, -18), xycoords=("data", "axes fraction"),
                    textcoords="offset points", ha="center", va="top",
                    fontsize=11, color=ghost, fontweight="bold")
    lo = min(min(today), min(prior)); hi = max(max(today), max(prior))
    ax.set_ylim(lo - (hi - lo) * 0.30, hi + (hi - lo) * 0.22)
    ax.set_xlim(-0.3, len(tenors) - 0.7)
    ax.axis("off")
    fig.patch.set_alpha(0)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(path, transparent=True, dpi=100, pad_inches=0)
    plt.close(fig)
    return path


# ============================================================ SOCIAL ART ====
# Social frames get line art with no axes, no ticks and no text: every label
# is set in HTML on top, so the typography stays under editorial control
# instead of being baked into a matplotlib bitmap.

def social_spark(y, path: str, size=(13, 3.4), color: str = INK,
                 lw: float = 5.5, fill: str | None = None,
                 crop: bool = True) -> str:
    """One line, edge to edge, transparent background."""
    y = np.asarray(y, dtype=float)
    fig, ax = plt.subplots(figsize=size)
    x = np.arange(len(y))
    if fill:
        ax.fill_between(x, y.min() - (float(np.ptp(y)) or 1) * .40, y,
                        color=fill, lw=0, alpha=0.16)
    ax.plot(x, y, color=color, lw=lw, solid_capstyle="round", zorder=3)
    ax.scatter([x[-1]], [y[-1]], s=lw * 26, color=color, zorder=4)
    ax.set_xlim(0, len(y) - 1)
    pad = (float(np.ptp(y)) or 1) * .16
    ax.set_ylim(y.min() - pad, y.max() + pad)
    ax.axis("off")
    fig.patch.set_alpha(0)
    fig.subplots_adjust(0, 0, 1, 1) if crop else None
    fig.savefig(path, transparent=True, bbox_inches=None if crop else "tight",
                pad_inches=0)
    plt.close(fig)
    return path


def social_curve(y, path: str, size=(11, 4.6), color: str = INK,
                 lw: float = 5.0) -> str:
    """Yield curve as pure line art. Tenor labels get set in HTML."""
    y = np.asarray(y, dtype=float)
    x = np.arange(len(y))
    fig, ax = plt.subplots(figsize=size)
    ax.plot(x, y, color=color, lw=lw, solid_capstyle="round", zorder=3)
    ax.scatter(x, y, s=lw * 22, color=color, zorder=4)
    ax.set_xlim(-.35, len(y) - .65)
    pad = (float(np.ptp(y)) or 1) * .22
    ax.set_ylim(y.min() - pad, y.max() + pad)
    ax.axis("off")
    fig.patch.set_alpha(0)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(path, transparent=True, pad_inches=0)
    plt.close(fig)
    return path
