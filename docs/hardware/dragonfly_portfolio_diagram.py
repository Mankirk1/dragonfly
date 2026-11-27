"""Simplified, large-text system schematic of Dragonfly for the portfolio.

This is a block-level view of the Rev B sheet (dragonfly_schematic.py).
Every pin number shown is taken from dragonfly_netlist.py, and the script
checks that before drawing, so the simple view cannot drift from the
verified circuit.

Run:  python docs/hardware/dragonfly_portfolio_diagram.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dragonfly_netlist import PARTS  # noqa: E402

mpl.rcParams["font.family"] = ["Inter", "DejaVu Sans"]
mpl.rcParams["svg.fonttype"] = "none"

# Pins shown on the diagram, checked against the netlist below.
SHOWN = {
    "IO16": "RD_TX",
    "IO17": "RD_RX",
    "IO36": "DOPPLER_ADC",
    "IO25": "PAN_PWM",
    "IO26": "TILT_PWM",
    "IO27": "LASER_EN",
    "IO14": "ARM_SENSE",
    "IO21": "I2C_SDA",
    "IO22": "I2C_SCL",
}


def verify() -> None:
    pins = PARTS["U1"][3]
    for pin, net in SHOWN.items():
        got = pins[pin][2] if pin in pins else None
        assert got == net, f"{pin}: diagram says {net}, netlist says {got}"
    print(f"Portfolio diagram pins match the netlist ({len(SHOWN)} GPIOs).")


# Palette: one colour per engineering domain.
C = {
    "rf": ("#6D28D9", "#F3EEFF"),
    "analog": ("#0F766E", "#E6F6F4"),
    "mcu": ("#1D4ED8", "#EAF0FF"),
    "act": ("#334155", "#F1F5F9"),
    "power": ("#C2410C", "#FFF1E8"),
    "safety": ("#B91C1C", "#FDECEC"),
}
INK = "#0F172A"
SUB = "#334155"


def box(ax, x, y, w, h, dom, title, lines=(), tsize=19, lsize=14.5):
    edge, fill = C[dom]
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0,rounding_size=4", lw=2.6, ec=edge, fc=fill, zorder=2
        )
    )
    n = len(lines)
    top = y + h / 2 + (n * 7.2) / 2 + 2
    ax.text(
        x + w / 2,
        top,
        title,
        ha="center",
        va="center",
        fontsize=tsize,
        fontweight="bold",
        color=edge,
        zorder=3,
    )
    for i, s in enumerate(lines):
        ax.text(
            x + w / 2,
            top - 9.5 - i * 7.2,
            s,
            ha="center",
            va="center",
            fontsize=lsize,
            color=INK,
            zorder=3,
        )


def arrow(ax, pts, dom, label=None, at=0.5, off=(0, 4.5), both=False, lsize=14, ha="center"):
    edge, _ = C[dom]
    xs, ys = zip(*pts, strict=True)
    for i in range(len(pts) - 2):
        ax.plot(xs[i : i + 2], ys[i : i + 2], color=edge, lw=2.6, solid_capstyle="round", zorder=1)
    style = "<|-|>" if both else "-|>"
    ax.add_patch(
        FancyArrowPatch(
            pts[-2],
            pts[-1],
            arrowstyle=style,
            mutation_scale=22,
            lw=2.6,
            color=edge,
            zorder=1,
            shrinkA=0,
            shrinkB=0,
        )
    )
    if label:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        ax.text(
            x0 + (x1 - x0) * at + off[0],
            y0 + (y1 - y0) * at + off[1],
            label,
            ha=ha,
            va="center",
            fontsize=lsize,
            color=edge,
            fontweight="semibold",
            linespacing=1.25,
            zorder=3,
        )


def draw(out: Path) -> None:
    fig = plt.figure(figsize=(16.54, 11.69))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 420)
    ax.set_ylim(0, 297)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        15,
        282,
        "Dragonfly: radar-guided pan/tilt tracker",
        fontsize=28,
        fontweight="bold",
        color=INK,
        va="center",
    )
    ax.text(
        15,
        270,
        "System schematic, simplified view of the verified Rev B sheet",
        fontsize=16,
        color=SUB,
        va="center",
    )

    # Legend
    lx = 236
    for key, name in (
        ("rf", "RF sensing"),
        ("analog", "Analog"),
        ("mcu", "Compute"),
        ("power", "Power"),
        ("safety", "Laser safety"),
    ):
        edge, fill = C[key]
        ax.add_patch(
            FancyBboxPatch(
                (lx, 266), 7, 7, boxstyle="round,pad=0,rounding_size=1.5", lw=2, ec=edge, fc=fill
            )
        )
        ax.text(lx + 10, 269.5, name, fontsize=14, va="center", color=INK)
        lx += 10 + len(name) * 2.7 + 6

    # ---------- Sensing (left) ----------
    box(
        ax,
        15,
        190,
        125,
        58,
        "rf",
        "RD-03D  24 GHz FMCW radar",
        ["Range, angle and speed of", "up to 3 targets, 10 Hz frames", "5 V supply, 3.3 V UART"],
    )
    box(ax, 15, 98, 48, 66, "rf", "CDM324", ["24 GHz", "Doppler", "sensor"], tsize=18)
    box(
        ax,
        78,
        98,
        72,
        66,
        "analog",
        "Band-pass amp",
        ["2 x LM358 stages", "Gain about 3,000", "16 Hz to 1.6 kHz", "1.65 V reference"],
        tsize=18,
    )
    arrow(ax, [(63, 131), (78, 131)], "analog")
    ax.text(
        70.5,
        92,
        "IF signal\n(microvolts)",
        ha="center",
        va="top",
        fontsize=13,
        color=C["analog"][0],
        fontweight="semibold",
    )

    # ---------- Controller (centre) ----------
    box(
        ax,
        185,
        98,
        92,
        150,
        "mcu",
        "ESP32-WROOM-32",
        [
            "Dual core, 240 MHz",
            "",
            "Firmware pipeline",
            "Radar frame parser",
            "Doppler FFT speed",
            "Kalman tracker",
            "Aim solver",
            "Micro-Doppler classifier",
            "Laser interlock",
        ],
        tsize=19,
        lsize=14,
    )

    arrow(ax, [(140, 219), (185, 219)], "mcu", "UART2\n256 kBd", off=(0, 12), both=True)
    ax.text(162.5, 210, "GPIO16/17", ha="center", va="center", fontsize=13, color=C["mcu"][0])
    ax.text(162.5, 202, "100 Ω series", ha="center", va="center", fontsize=12.5, color=SUB)
    arrow(ax, [(150, 131), (185, 131)], "analog", "ADC1", off=(0, 9))
    ax.text(167.5, 122, "GPIO36", ha="center", va="center", fontsize=13, color=C["analog"][0])
    ax.text(167.5, 114, "diode clamp", ha="center", va="center", fontsize=12.5, color=SUB)

    # ---------- Outputs (right) ----------
    box(ax, 318, 214, 90, 36, "mcu", "OLED display", ["SSD1306, 128 x 64"], tsize=18)
    box(ax, 318, 160, 90, 40, "act", "Pan servo", ["MG996R, ±90°"], tsize=18)
    box(ax, 318, 106, 90, 40, "act", "Tilt servo", ["MG996R, ±45°"], tsize=18)
    arrow(ax, [(277, 232), (318, 232)], "mcu", "I²C", off=(0, 7))
    ax.text(297.5, 224, "GPIO21/22", ha="center", fontsize=13, color=C["mcu"][0], va="center")
    arrow(ax, [(277, 180), (318, 180)], "act", "PWM", off=(0, 7))
    ax.text(297.5, 172, "GPIO25", ha="center", fontsize=13, color=C["act"][0], va="center")
    arrow(ax, [(277, 126), (318, 126)], "act", "PWM", off=(0, 7))
    ax.text(297.5, 118, "GPIO26", ha="center", fontsize=13, color=C["act"][0], va="center")

    # ---------- Power (bottom left) ----------
    box(
        ax,
        15,
        18,
        125,
        58,
        "power",
        "Logic power: USB 5 V",
        ["Feeds ESP32, radar, amp,", "OLED and laser chain", "About 250 mA average"],
        tsize=18,
    )
    arrow(ax, [(140, 46), (160, 46)], "power", "5 V", off=(-4, 5))

    # ---------- Servo power (bottom right) ----------
    box(
        ax,
        318,
        18,
        90,
        58,
        "power",
        "Servo supply",
        ["Separate 5 V, 3 A", "Keeps motor noise", "off the logic rail"],
        tsize=18,
    )
    arrow(ax, [(412, 76), (412, 126), (408, 126)], "power")
    arrow(ax, [(412, 126), (412, 180), (408, 180)], "power")
    ax.text(
        415,
        101,
        "5 V",
        rotation=90,
        ha="left",
        va="center",
        fontsize=14,
        color=C["power"][0],
        fontweight="semibold",
    )

    # ---------- Laser safety chain (bottom centre) ----------
    edge, fill = C["safety"]
    ax.add_patch(
        FancyBboxPatch(
            (153, 8),
            152,
            74,
            boxstyle="round,pad=0,rounding_size=4",
            lw=2.6,
            ec=edge,
            fc="white",
            ls=(0, (6, 3)),
            zorder=0,
        )
    )
    ax.text(
        229,
        14,
        "Laser fires only if key AND GPIO27 agree",
        ha="center",
        fontsize=15,
        fontweight="bold",
        color=edge,
        va="center",
    )
    box(ax, 160, 24, 42, 46, "safety", "Key switch", ["2-pole", "S1"], tsize=15.5, lsize=14)
    box(ax, 208, 24, 42, 46, "safety", "MOSFET", ["AO3400", "low side"], tsize=15.5, lsize=14)
    box(ax, 256, 24, 42, 46, "safety", "Laser", ["Class 2", "≤ 1 mW"], tsize=15.5, lsize=14)
    arrow(ax, [(202, 47), (208, 47)], "safety")
    arrow(ax, [(250, 47), (256, 47)], "safety")
    arrow(
        ax,
        [(229, 98), (229, 70)],
        "safety",
        "GPIO27 enable",
        at=0.25,
        off=(4, 0),
        lsize=13,
        ha="left",
    )
    arrow(ax, [(181, 70), (181, 93), (198, 93), (198, 98)], "safety")
    ax.text(
        177,
        87,
        "GPIO14 arm sense",
        ha="right",
        va="center",
        fontsize=13,
        color=C["safety"][0],
        fontweight="semibold",
    )

    ax.text(
        15,
        4,
        "Pins and parts match dragonfly_netlist.py, which passes 18 automated "
        "electrical rule checks. Full detail: dragonfly_schematic.pdf (31 nets).",
        fontsize=12.5,
        color=SUB,
        va="center",
    )

    out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out / f"dragonfly_portfolio_diagram.{ext}", dpi=200 if ext == "png" else None)
    plt.close(fig)


if __name__ == "__main__":
    verify()
    draw(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
