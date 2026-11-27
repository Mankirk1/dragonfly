"""Dragonfly system schematic (Rev A).

Draws the full system schematic on one A3 landscape sheet with schemdraw
(component symbols) and matplotlib (frames, modules, net labels, title block).

Usage:  python dragonfly_schematic.py [outdir]
Writes dragonfly_schematic.{pdf,svg,png}.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import schemdraw
import schemdraw.elements as elm
from matplotlib.patches import Polygon, Rectangle

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
FONT = "Inter"
W, H = 168.0, 118.8  # drawing units, A3 aspect

INK = "#1a1a1a"
NET = "#1F4E79"
NETFILL = "#EAF1F8"
PWR = "#8B1A1A"
FRAME = "#8C8C8C"
MUTED = "#555555"
LW = 1.1

plt.rcParams["font.family"] = FONT
fig = plt.figure(figsize=(16.54, 11.69))
ax = fig.add_axes([0, 0, 1, 1])
ops = []  # deferred matplotlib drawing


# ---------------------------------------------------------------- primitives
def wire(*pts):
    xs, ys = zip(*pts, strict=True)
    ops.append(lambda: ax.plot(xs, ys, color=INK, lw=LW, solid_capstyle="round", zorder=3))


def dot(x, y):
    ops.append(lambda: ax.add_patch(plt.Circle((x, y), 0.32, color=INK, zorder=5)))


def text(
    x, y, s, size=7, color=INK, ha="left", va="center", weight="normal", style="normal", rot=0, z=6
):
    ops.append(
        lambda: ax.text(
            x,
            y,
            s,
            fontsize=size,
            color=color,
            ha=ha,
            va=va,
            fontweight=weight,
            fontstyle=style,
            rotation=rot,
            zorder=z,
        )
    )


def flag(x, y, name, side):
    """Net label attached to a wire end at (x, y); body extends to `side` ('l' or 'r')."""
    h = 1.15
    w = 0.62 * len(name) + 1.6
    s = 1 if side == "r" else -1
    pts = [
        (x, y),
        (x + s * 0.7, y + h / 2),
        (x + s * w, y + h / 2),
        (x + s * w, y - h / 2),
        (x + s * 0.7, y - h / 2),
    ]
    ops.append(
        lambda: ax.add_patch(Polygon(pts, closed=True, fc=NETFILL, ec=NET, lw=0.9, zorder=4))
    )
    text(x + s * (w + 0.7) / 2, y, name, size=6.6, color=NET, ha="center", weight="semibold")


def port(x, y, name, up=True, stub=1.6):
    """Power-port symbol: stub from (x, y), bar, rail name."""
    s = 1 if up else -1
    wire((x, y), (x, y + s * stub))
    yb = y + s * stub
    ops.append(lambda: ax.plot([x - 0.9, x + 0.9], [yb, yb], color=PWR, lw=1.6, zorder=4))
    text(
        x,
        yb + s * 0.9,
        name,
        size=6.6,
        color=PWR,
        ha="center",
        weight="semibold",
        va="bottom" if up else "top",
    )


def gnd(x, y, stub=1.0):
    wire((x, y), (x, y - stub))
    yb = y - stub
    for i, half in enumerate((1.0, 0.62, 0.25)):
        yy = yb - i * 0.38
        ops.append(
            lambda yy=yy, half=half: ax.plot(
                [x - half, x + half], [yy, yy], color=INK, lw=1.2, zorder=4
            )
        )


def frame(x0, y0, x1, y1, tag, title):
    ops.append(
        lambda: ax.add_patch(
            Rectangle(
                (x0, y0), x1 - x0, y1 - y0, fill=False, ec=FRAME, lw=0.8, ls=(0, (4, 2)), zorder=1
            )
        )
    )
    ops.append(
        lambda: ax.add_patch(Rectangle((x0, y1 - 2.6), 2.6, 2.6, fc="#2B2B2B", ec="none", zorder=2))
    )
    text(x0 + 1.3, y1 - 1.3, tag, size=8, color="white", ha="center", weight="bold")
    text(x0 + 3.6, y1 - 1.3, title, size=8, weight="bold", color="#2B2B2B")


def module(x0, y0, w, h, ref, value, pins, desc=None):
    """Box with pins. pins: list of (side, pos, name) where side in L/R/T/B and pos is
    the y (L/R) or x (T/B) coordinate. Returns {name: pin-end (x, y)}."""
    ops.append(
        lambda: ax.add_patch(Rectangle((x0, y0), w, h, fc="#FBFBF8", ec=INK, lw=1.3, zorder=2))
    )
    text(x0, y0 + h + 0.8, ref, size=7.5, weight="bold", va="bottom")
    text(x0 + len(ref) * 0.75 + 0.8, y0 + h + 0.8, value, size=7, va="bottom", color=MUTED)
    if desc:
        text(
            x0 + w / 2,
            y0 + h / 2 if not any(p[0] in "LR" for p in pins) else y0 + 1.0,
            desc,
            size=5.8,
            color=MUTED,
            ha="center",
            style="italic",
        )
    ends = {}
    L = 2.0
    for side, pos, name in pins:
        if side == "L":
            a, b = (x0, pos), (x0 - L, pos)
            text(x0 + 0.6, pos, name, size=6.2)
        elif side == "R":
            a, b = (x0 + w, pos), (x0 + w + L, pos)
            text(x0 + w - 0.6, pos, name, size=6.2, ha="right")
        elif side == "T":
            a, b = (pos, y0 + h), (pos, y0 + h + L)
            text(pos, y0 + h - 0.6, name, size=6.2, ha="center", va="top")
        else:
            a, b = (pos, y0), (pos, y0 - L)
            text(pos, y0 + 0.6, name, size=6.2, ha="center", va="bottom")
        wire(a, b)
        ends[name] = b
    return ends


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dragonfly_netlist import NETS, PARTS, PASSIVES  # noqa: E402

_flag, _port = flag, port
DRAWN_NETS = set()


def flag(x, y, name, side):
    assert name in NETS, f"net label {name} is not in the netlist"
    DRAWN_NETS.add(name)
    _flag(x, y, name, side)


def port(x, y, name, up=True, stub=1.6):
    assert name in NETS, f"rail {name} is not in the netlist"
    DRAWN_NETS.add(name)
    _port(x, y, name, up, stub)


def lab(ref, sep="\n"):
    """Designator and value straight from the netlist, so the drawing cannot drift."""
    return f"{ref}{sep}{PASSIVES[ref][0]}".replace(" 10 V", "\n10 V")


S = 1.45  # symbol scale
d = schemdraw.Drawing(canvas=ax, show=False)
d.config(fontsize=6.8, font=FONT, lw=LW, color=INK)


def part(e, scale=S):
    return d.add(e.scale(scale))


def pinno(x, y, n, ha="left"):
    text(x, y, n, size=5, color=MUTED, ha=ha, va="bottom")


# ---------------------------------------------------------------- A  RD-03D
frame(5, 90, 58, 114, "A", "PRIMARY TRACKING RADAR")
p = module(
    12,
    96,
    12,
    10,
    "M1",
    "RD-03D",
    [("T", 21, "5V"), ("B", 21, "GND"), ("R", 103, "TX"), ("R", 99, "RX")],
)
port(*p["5V"], "+5V")
gnd(*p["GND"])
wire(p["TX"], (31, 103))
flag(31, 103, "RD_TX", "r")
wire(p["RX"], (31, 99))
flag(31, 99, "RD_RX", "r")
text(13.0, 101, "24 GHz\nFMCW", size=6, color=MUTED)
text(
    30,
    95.2,
    "Ai-Thinker RD-03D, 24 GHz FMCW\nUART 256 000 Bd 8N1, 3.3 V logic\nRange, X/Y bearing and speed, up to 3 targets",
    size=6,
    color=MUTED,
    va="top",
)

# ---------------------------------------------------------------- B  POWER
frame(5, 62, 58, 88, "B", "POWER DISTRIBUTION")
p = module(9, 71, 7, 9, "J1", "DC jack", [("R", 78, "+"), ("R", 73, "−")])
text(12.5, 75.5, "5 V\n≥ 5 A", size=6, color=MUTED, ha="center")
wire(p["+"], (27, 78))
dot(22, 78)
part(elm.Capacitor(polar=True).at((22, 78)).down(4).label(lab("C1"), loc="bottom", ofst=0.5))
gnd(22, 74)
port(27, 78, "+5V_SERVO")
wire(p["−"], (19, 73))
gnd(19, 73)
text(
    9,
    67.4,
    "External servo supply (5 V wall adapter or UBEC).\nKeeps servo stall current (≈ 2.5 A each) off USB.",
    size=6,
    color=MUTED,
    va="center",
)
tx, ty = 31, 84.2
rows = [
    ("RAIL", "SOURCE", "LOADS"),
    ("+5V_SERVO", "J1 external 5 V", "M3, M4"),
    ("+5V", "U1 USB VBUS", "M1, M2, M5, U2, U3"),
    ("+3V3", "U1 on-board LDO", "M6, R7, D1"),
    ("VREF", "U3A buffer, 1.65 V", "AFE bias"),
    ("GND", "common, star at U1", "all"),
]
for i, (a_, b_, c_) in enumerate(rows):
    yy = ty - i * 2.2
    hdr = i == 0
    text(tx, yy, a_, size=6, weight="bold", color=INK if hdr else PWR)
    text(tx + 8.2, yy, b_, size=6, weight="bold" if hdr else "normal")
    text(tx + 18.5, yy, c_, size=6, weight="bold" if hdr else "normal")
ops.append(lambda: ax.plot([tx, 56.5], [ty - 1.1, ty - 1.1], color=FRAME, lw=0.6, zorder=3))

# ---------------------------------------------------------------- D  ESP32
frame(60, 62, 116, 114, "C", "CONTROLLER")
p = module(
    78,
    68,
    20,
    40,
    "U1",
    "ESP32-WROOM-32 DevKit (38-pin)",
    [
        ("L", 104, "5V"),
        ("L", 100, "3V3"),
        ("L", 93, "GPIO36 / VP"),
        ("L", 86, "GPIO16 / RX2"),
        ("L", 82, "GPIO17 / TX2"),
        ("R", 104, "GPIO25"),
        ("R", 100, "GPIO26"),
        ("R", 93, "GPIO27"),
        ("R", 89, "GPIO14"),
        ("R", 82, "GPIO21 / SDA"),
        ("R", 78, "GPIO22 / SCL"),
        ("R", 72, "USB"),
        ("B", 88, "GND"),
    ],
)
wire(p["5V"], (72, 104))
port(72, 104, "+5V")
wire(p["3V3"], (67, 100))
port(67, 100, "+3V3")
wire(p["GPIO36 / VP"], (73, 93))
flag(73, 93, "DOPPLER_ADC", "l")
wire(p["GPIO16 / RX2"], (73, 86))
flag(73, 86, "RD_TX", "l")
wire(p["GPIO17 / TX2"], (73, 82))
flag(73, 82, "RD_RX", "l")
wire(p["GPIO25"], (103, 104))
flag(103, 104, "PAN_PWM", "r")
wire(p["GPIO26"], (103, 100))
flag(103, 100, "TILT_PWM", "r")
wire(p["GPIO27"], (103, 93))
flag(103, 93, "LASER_EN", "r")
wire(p["GPIO14"], (103, 89))
flag(103, 89, "ARM_SENSE", "r")
wire(p["GPIO21 / SDA"], (103, 82))
flag(103, 82, "I2C_SDA", "r")
wire(p["GPIO22 / SCL"], (103, 78))
flag(103, 78, "I2C_SCL", "r")
gnd(*p["GND"])
ux, uy = p["USB"]
wire((ux, uy), (ux + 2.5, uy))
ops.append(
    lambda: ax.annotate(
        "",
        xy=(ux + 6.5, uy),
        xytext=(ux + 2.5, uy),
        arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=LW),
        zorder=3,
    )
)
text(ux + 7.2, uy + 0.6, "Host PC", size=6.6, weight="semibold")
text(
    ux + 7.2,
    uy - 0.9,
    "micro-USB: power,\nflashing, telemetry\n460 800 Bd",
    size=5.8,
    color=MUTED,
    va="top",
)
for yy, s_ in [(93, "ADC1_CH0"), (86, "UART2"), (82, "UART2")]:
    text(75.5, yy + 0.9, s_, size=5.2, color=MUTED, ha="center")
for yy, s_ in [
    (104, "PWM"),
    (100, "PWM"),
    (93, "HIGH = on"),
    (89, "pull-up"),
    (82, "I²C"),
    (78, "I²C"),
]:
    text(100.5, yy + 0.9, s_, size=5.2, color=MUTED, ha="center")
text(
    88, 106.6, "Dual-core 240 MHz · Wi-Fi / BT", size=5.6, color=MUTED, ha="center", style="italic"
)
text(
    62,
    70.5,
    "Pin map matches\nfirmware/src/board.hpp.\nGPIO21/22 are the ESP32\nWire defaults (to be added\nto board.hpp).",
    size=5.6,
    color=MUTED,
    va="center",
)

# ---------------------------------------------------------------- C  ANALOG FRONT END
frame(5, 19, 116, 60, "D", "CW DOPPLER SENSOR AND ANALOG FRONT END")
Y = 49.0
p = module(8, 44, 9, 10, "M2", "CDM324", [("R", 52, "VCC"), ("R", Y, "IF"), ("R", 46, "GND")])
text(12.5, 50.5, "24 GHz\nCW", size=6, color=MUTED, ha="center")
wire(p["VCC"], (21, 52), (21, 54))
port(21, 54, "+5V", stub=1.0)
wire(p["GND"], (21, 46))
gnd(21, 46)
wire(p["IF"], (22, Y))
part(elm.Capacitor().at((22, Y)).right(4).label(lab("C3"), loc="top", ofst=0.3))
wire((26, Y), (34, Y))
dot(29, Y)
part(elm.Resistor().at((29, Y)).down(5).label(lab("R1"), loc="bottom", ofst=0.3))
port(29, Y - 5, "VREF", up=False, stub=0.8)


def opamp(x, y, ref, pins):
    o = part(elm.Opamp(leads=True).right().flip().anchor("in2").at((x, y)))
    A = {k: tuple(v) for k, v in o.absanchors.items()}
    text(x + 1.6, y + 2.7, ref, size=7, weight="bold")
    text(x + 1.6, y + 1.5, "LM358", size=6.2, color=MUTED)
    pinno(A["in2"][0] + 0.15, A["in2"][1] + 0.05, pins[0])
    pinno(A["in1"][0] + 0.15, A["in1"][1] + 0.05, pins[1])
    pinno(A["out"][0] - 0.15, A["out"][1] + 0.05, pins[2], ha="right")
    return A


def amp_stage(A, nx, fb_parts, cfb, rg, cdc, xr, y_r, y_c, rg_len=4):
    """Non-inverting stage: feedback R (and optional trimmer) at y_r, C at y_c below the op-amp."""
    n1, o = A["in1"], A["out"]
    wire(n1, (nx, n1[1]), (nx, y_c))
    dot(nx, y_r)
    x = nx
    for kind, ref, ln in fb_parts:
        if kind == "R":
            part(elm.Resistor().at((x, y_r)).right(ln).label(lab(ref, "  "), loc="top", ofst=0.3))
        else:
            pot = part(
                elm.Potentiometer()
                .at((x, y_r))
                .right(ln)
                .label(f"{ref}  {PARTS[ref][0].split()[0]} kΩ", loc="top", ofst=0.3)
            )
            tp = pot.absanchors["tap"]
            wire(tuple(tp), (tp[0], tp[1] + 0.7), (x + ln, tp[1] + 0.7), (x + ln, y_r))
            dot(x + ln, y_r)
        x += ln
    wire((x, y_r), (xr, y_r))
    part(elm.Capacitor().at((nx, y_c)).right(xr - nx).label(lab(cfb, "  "), loc="top", ofst=0.3))
    wire((xr, y_c), (xr, o[1]))
    dot(xr, y_r)
    dot(nx, y_c)
    part(elm.Resistor().at((nx, y_c)).down(rg_len).label(lab(rg), loc="bottom", ofst=0.3))
    part(
        elm.Capacitor().at((nx, y_c - rg_len)).down(rg_len).label(lab(cdc), loc="bottom", ofst=0.3)
    )
    port(nx, y_c - 2 * rg_len, "VREF", up=False, stub=0.8)


A1 = opamp(34, Y, "U2A", ("3", "2", "1"))
amp_stage(A1, 32.5, [("R", "R3", 9)], "C4", "R2", "C5", xr=41.5, y_r=42, y_c=37, rg_len=3.6)
wire(A1["out"], (47, A1["out"][1]))
dot(41.5, A1["out"][1])

Y2 = A1["out"][1]
A2 = opamp(47, Y2, "U2B", ("5", "6", "7"))
amp_stage(
    A2,
    45.5,
    [("R", "R5", 5), ("P", "RV1", 5.5)],
    "C6",
    "R4",
    "C7",
    xr=56,
    y_r=41.1,
    y_c=36.1,
    rg_len=3.6,
)
Y3 = A2["out"][1]
wire(A2["out"], (58, Y3))
dot(56, Y3)
part(elm.Resistor().at((58, Y3)).right(4).label(lab("R6"), loc="top", ofst=0.3))
wire((62, Y3), (76, Y3))
dot(65, Y3)
dot(70, Y3)
part(elm.Capacitor().at((65, Y3)).down(4).label(lab("C8"), loc="bottom", ofst=0.3))
gnd(65, Y3 - 4)
part(elm.Schottky().at((70, Y3)).up(3.6))
port(70, Y3 + 3.6, "+3V3", stub=0.8)
part(elm.Schottky().at((70, Y3 - 3.6)).up(3.6))
gnd(70, Y3 - 3.6)
text(71.3, Y3 + 1.8, "D1B", size=6.5, weight="bold")
text(71.3, Y3 - 1.8, "D1A", size=6.5, weight="bold")
text(71.3, Y3 - 5.2, "D1  BAT54S", size=6, color=MUTED)
pinno(69.5, Y3 + 3.6 - 1.0, "2", ha="right")
pinno(69.5, Y3 + 0.15, "3", ha="right")
pinno(69.5, Y3 - 3.6 + 0.15, "1", ha="right")
flag(76, Y3, "DOPPLER_ADC", "r")

# op-amp supply pins (bottom-left)
for ref, x, cref in (("U2", 61.0, "C10"), ("U3", 75.0, "C11")):
    pp = module(x, 22.5, 6, 5, "", "", [("T", x + 1.5, "8"), ("B", x + 1.5, "4")])
    text(x + 3.9, 25.0, f"{ref}\nLM358", size=6, ha="center", weight="semibold")
    port(*pp["8"], "+5V", stub=1.0)
    gnd(*pp["4"], stub=0.6)
    cx = x + 8.5
    wire(pp["8"], (cx, pp["8"][1]))
    dot(*pp["8"])
    part(elm.Capacitor().at((cx, pp["8"][1])).down(4).label(lab(cref), loc="bottom", ofst=0.3))
    gnd(cx, pp["8"][1] - 4, stub=0.6)
text(61, 34.6, "Op-amp supply and decoupling", size=6, weight="semibold", color=MUTED)

# design summary (right column)
bx = 87.5
summary = [
    ("Signal chain", True),
    ("Stage 1  G = 1 + R3/R2 = 101  (40 dB)", False),
    ("Stage 2  G = 1 + (R5+RV1)/R4 = 22 to 44", False),
    ("High-pass  R1·C3, R2·C5, R4·C7 ≈ 16 Hz", False),
    ("Low-pass  R3·C4, R6·C8 ≈ 1.6 kHz", False),
    ("Doppler at 24.125 GHz ≈ 161 Hz per m/s", False),
    ("0.2 to 5 m/s → 32 to 805 Hz, in band", False),
    ("D1 + R6 clamp the ADC pin to 0 to 3.3 V", False),
]
for i, (s_, b_) in enumerate(summary):
    text(
        bx,
        57.0 - i * 1.75,
        s_,
        size=6.2 if b_ else 5.7,
        weight="bold" if b_ else "normal",
        color=INK if b_ else MUTED,
    )

# VREF generator (U3A buffer)
VX = 89.0
port(VX, 37.5, "+3V3", stub=1.0)
part(elm.Resistor().at((VX, 37.5)).down(4).label(lab("R7"), loc="bottom", ofst=0.3))
dot(VX, 33.5)
part(elm.Resistor().at((VX, 33.5)).down(4).label(lab("R8"), loc="bottom", ofst=0.3))
gnd(VX, 29.5)
wire((VX, 33.5), (100, 33.5))
dot(94, 33.5)
part(elm.Capacitor().at((94, 33.5)).down(4).label(lab("C9"), loc="bottom", ofst=0.3))
gnd(94, 29.5)
A3 = opamp(100, 33.5, "U3A", ("3", "2", "1"))
wire(A3["in1"], (99, A3["in1"][1]), (99, 28.8), (106.5, 28.8), (106.5, A3["out"][1]))
wire(A3["out"], (108, A3["out"][1]))
dot(106.5, A3["out"][1])
flag(108, A3["out"][1], "VREF", "r")
text(108, A3["out"][1] - 1.7, "1.65 V", size=5.8, color=MUTED)
text(
    87.5,
    23.4,
    "U3B unused, tied off: pin 5 to VREF,\npin 6 to pin 7 (not drawn).",
    size=5.6,
    color=MUTED,
)
text(87.5, 41.6, "Mid-rail reference", size=6, weight="semibold", color=MUTED)

# ---------------------------------------------------------------- E  SERVOS
frame(118, 88, 164, 114, "E", "PAN / TILT GIMBAL")
m3 = module(
    136,
    103,
    10,
    7,
    "M3",
    "MG996R  pan",
    [("L", 106.5, "SIG"), ("R", 108.5, "V+"), ("R", 104.5, "GND")],
)
m4 = module(
    136,
    92,
    10,
    7,
    "M4",
    "MG996R  tilt",
    [("L", 95.5, "SIG"), ("R", 97.5, "V+"), ("R", 93.5, "GND")],
)
wire(m3["SIG"], (128, 106.5))
flag(128, 106.5, "PAN_PWM", "l")
wire(m4["SIG"], (128, 95.5))
flag(128, 95.5, "TILT_PWM", "l")
wire(m3["GND"], (149.5, 104.5))
gnd(149.5, 104.5, stub=0.6)
wire(m4["GND"], (149.5, 93.5))
gnd(149.5, 93.5, stub=0.6)
wire(m3["V+"], (153, 108.5))
wire(m4["V+"], (153, 97.5))
wire((153, 97.5), (153, 110))
port(153, 110, "+5V_SERVO", stub=1.0)
dot(153, 108.5)
dot(153, 101)
wire((153, 101), (157, 101))
part(elm.Capacitor(polar=True).at((157, 101)).down(3.5).label(lab("C2"), loc="bottom", ofst=0.5))
gnd(157, 97.5)
text(
    119.5,
    90.2,
    "50 Hz PWM, 0.5 to 2.5 ms pulses\nRadars stay fixed; the gimbal moves the laser.",
    size=5.6,
    color=MUTED,
    va="center",
)

# ---------------------------------------------------------------- F  LASER
frame(118, 58, 164, 86, "F", "LASER INDICATOR AND SAFETY INTERLOCK")
sw = d.add(elm.SwitchDpst().right().scale(2.4).at((131, 80)))
a = {k: tuple(v) for k, v in sw.absanchors.items()}
port(127, 80, "+5V", stub=1.4)
wire((127, 80), a["p1"])
wire(a["t1"], (141, 80), (141, 77))
flag(129, a["p2"][1], "ARM_SENSE", "l")
wire((129, a["p2"][1]), a["p2"])
wire(a["t2"], (a["t2"][0] + 0.8, a["p2"][1]), (a["t2"][0] + 0.8, a["p2"][1] - 0.6))
gnd(a["t2"][0] + 0.8, a["p2"][1] - 0.6, stub=0.6)
text(130.2, 82.6, "S1", size=7.5, weight="bold")
text(132.6, 82.6, "key switch, 2-pole", size=6, color=MUTED)
text(a["t1"][0] + 0.4, 80.6, "A", size=5.6, color=MUTED)
text(a["t2"][0] + 0.4, a["p2"][1] + 0.6, "B", size=5.6, color=MUTED)
text(135.2, 80.6, "LASER_PWR", size=5.2, color=MUTED)
m5 = module(137, 69, 8, 6, "M5", "", [("T", 141, "+"), ("B", 141, "−")])
text(141, 72, "650 nm  ≤ 1 mW", size=5.6, ha="center", color=MUTED)
text(146.5, 73.4, "Laser module, 5 V\nIEC 60825-1 Class 2", size=6, color=MUTED, va="center")
wire(m5["−"], (141, 66))


def nmos(x, yd):
    """Enhancement N-MOSFET drawn directly: drain at (x, yd), source 3 below, gate on the left."""
    ys = yd - 3.0
    ym = yd - 1.5
    wire((x, yd), (x, yd - 0.8), (x - 0.75, yd - 0.8))
    wire((x, ys), (x, ys + 0.8), (x - 0.75, ys + 0.8))
    wire((x, ym), (x, ys + 0.8))
    for y0, y1 in ((yd - 0.45, yd - 1.15), (ym - 0.3, ym + 0.3), (ys + 0.45, ys + 1.15)):
        ops.append(
            lambda y0=y0, y1=y1: ax.plot(
                [x - 0.75, x - 0.75], [y0, y1], color=INK, lw=1.6, zorder=4
            )
        )
    ops.append(
        lambda: ax.plot([x - 1.2, x - 1.2], [yd - 0.6, ys + 0.6], color=INK, lw=1.6, zorder=4)
    )
    ops.append(
        lambda: ax.annotate(
            "",
            xy=(x - 0.8, ym),
            xytext=(x, ym),
            arrowprops=dict(arrowstyle="-|>", color=INK, lw=LW, mutation_scale=7),
            zorder=4,
        )
    )
    wire((x - 2.2, ym), (x - 1.2, ym))
    return {"drain": (x, yd), "source": (x, ys), "gate": (x - 2.2, ym), "center": (x, ym)}


qa = nmos(141, 66)
gnd(141, qa["source"][1], stub=0.6)
text(142.8, qa["center"][1] + 0.6, "Q1", size=7, weight="bold")
text(142.8, qa["center"][1] - 0.7, "AO3400", size=6, color=MUTED)
gx, gy = qa["gate"]
wire((gx, gy), (134, gy))
dot(134, gy)
part(elm.Resistor().at((134, gy)).left(4.5).label(lab("R9", "  "), loc="top", ofst=0.3))
flag(129.5, gy, "LASER_EN", "l")
part(elm.Resistor().at((134, gy)).down(3.5).label(lab("R10"), loc="top", ofst=0.3))
gnd(134, gy - 3.5, stub=0.6)
text(147, 66.6, "SAFETY", size=6.2, weight="bold", color=PWR)
text(
    147,
    65.2,
    "S1A cuts laser power whatever\nthe firmware does. S1B tells\nthe firmware; it must be\nre-armed after every fault.\nR10 keeps Q1 off during boot.",
    size=5.6,
    color=MUTED,
    va="top",
)

# ---------------------------------------------------------------- G  OLED
frame(118, 31, 164, 56, "G", "STATUS DISPLAY")
m6 = module(
    140,
    38,
    12,
    11,
    "M6",
    "SSD1306 OLED",
    [("L", 46, "VCC"), ("L", 43, "SCL"), ("L", 40, "SDA"), ("B", 146, "GND")],
)
text(146, 45.0, '0.96"\n128 × 64', size=6, color=MUTED, ha="center")
wire(m6["VCC"], (133, 46))
port(133, 46, "+3V3", stub=1.2)
wire(m6["SCL"], (131, 43))
flag(131, 43, "I2C_SCL", "l")
wire(m6["SDA"], (131, 40))
flag(131, 40, "I2C_SDA", "l")
gnd(*m6["GND"], stub=0.6)
text(
    119.5,
    34.2,
    "I²C address 0x3C, 400 kHz. Shows range, velocity,\nclass and lock state. SDA/SCL pull-ups on the module.",
    size=5.6,
    color=MUTED,
    va="center",
)

# ---------------------------------------------------------------- NOTES
frame(5, 4, 116, 17, "N", "NOTES")
notes = [
    "1.  Netlist, BOM and electrical rule checks: dragonfly_netlist.py (all checks pass). Pin map matches firmware/src/board.hpp.",
    "2.  +5V_SERVO comes from J1 only. Servo and logic grounds join at one point near U1 so servo current stays out of the analog ground.",
    "3.  Laser is IEC 60825-1 Class 2 (≤ 1 mW); see docs/safety/laser-interlock.md. Test T9 must pass before any trial with a person.",
    "4.  Analog values are nominal. Set RV1 on the bench so the ADC never clips. C5, C7 ceramic X5R; C1, C2 electrolytic.",
    "5.  Resistors 0.25 W 5 %. Net labels with the same name are connected. GPIO36 is input-only on ADC1 (ADC2 is unusable with Wi-Fi).",
]
for i, s_ in enumerate(notes):
    text(7, 13.0 - i * 2.05, s_, size=6.1, color=INK)

missing = (
    set(NETS)
    - DRAWN_NETS
    - {
        "GND",
        "DOPPLER_IF",
        "AMP1_IN",
        "AMP1_FB",
        "AMP1_RG",
        "AMP1_OUT",
        "AMP2_FB",
        "AMP2_RV",
        "AMP2_RG",
        "AMP2_OUT",
        "VREF_DIV",
        "U3B_FB",
        "LASER_PWR",
        "LASER_SW",
        "LASER_GATE",
    }
)
assert not missing, f"netlist nets never labelled on the sheet: {missing}"

# ---------------------------------------------------------------- TITLE BLOCK
tbx0, tby0, tbx1, tby1 = 118, 4, 164, 29
ops.append(
    lambda: ax.add_patch(
        Rectangle((tbx0, tby0), tbx1 - tbx0, tby1 - tby0, fill=False, ec=INK, lw=1.4, zorder=2)
    )
)


def hline(y, x0=tbx0, x1=tbx1):
    ops.append(lambda: ax.plot([x0, x1], [y, y], color=INK, lw=0.7, zorder=2))


def vline(x, y0, y1):
    ops.append(lambda: ax.plot([x, x], [y0, y1], color=INK, lw=0.7, zorder=2))


hline(20.5)
hline(15.5)
hline(11)
hline(7.5)
vline(141, 4, 15.5)
vline(153, 4, 11)
text(119.5, 26.6, "DRAGONFLY", size=15, weight="bold")
text(119.5, 23.6, "Doppler Radar Detection and Tracking System", size=7.6, color=INK)
text(119.5, 21.8, "INSA Lyon · IBMMAE final-year project", size=6.4, color=MUTED)
text(119.5, 19.4, "TITLE", size=5, color=MUTED)
text(119.5, 17.4, "System schematic: sensing, control, actuation", size=8, weight="semibold")


def cell(x, y, label, value, size=7):
    text(x, y + 2.0, label, size=5, color=MUTED)
    text(x, y + 0.5, value, size=size, weight="semibold")


cell(119.5, 12.0, "DRAWN BY", "A. Kirkman")
cell(142.5, 12.0, "DATE", "2026-11-27")
cell(119.5, 7.8, "FILE", "dragonfly_schematic.py", size=6.4)
cell(142.5, 7.8, "SIZE", "A3")
cell(154.5, 7.8, "REV", "A")
cell(119.5, 4.4, "CHECKED", "dragonfly_netlist.py ERC", size=6.4)
cell(142.5, 4.4, "SCALE", "NTS")
cell(154.5, 4.4, "SHEET", "1 of 1")


# ---------------------------------------------------------------- BORDER + ZONES
def border():
    ax.add_patch(Rectangle((1.5, 1.5), W - 3, H - 3, fill=False, ec=INK, lw=1.6, zorder=1))
    ax.add_patch(Rectangle((3, 3), W - 6, H - 6, fill=False, ec=INK, lw=0.6, zorder=1))
    ncol, nrow = 8, 6
    for i in range(ncol):
        x = 3 + (W - 6) * (i + 0.5) / ncol
        for y in (2.25, H - 2.25):
            ax.text(x, y, str(i + 1), fontsize=6, ha="center", va="center", color=MUTED)
        if i:
            xx = 3 + (W - 6) * i / ncol
            ax.plot([xx, xx], [1.5, 3], color=INK, lw=0.6)
            ax.plot([xx, xx], [H - 3, H - 1.5], color=INK, lw=0.6)
    for j in range(nrow):
        y = 3 + (H - 6) * (j + 0.5) / nrow
        for x in (2.25, W - 2.25):
            ax.text(x, y, "ABCDEF"[nrow - 1 - j], fontsize=6, ha="center", va="center", color=MUTED)
        if j:
            yy = 3 + (H - 6) * j / nrow
            ax.plot([1.5, 3], [yy, yy], color=INK, lw=0.6)
            ax.plot([W - 3, W - 1.5], [yy, yy], color=INK, lw=0.6)


ops.append(border)

# ---------------------------------------------------------------- RENDER
d.draw(canvas=ax)
for op in ops:
    op()
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")
OUT.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT / "dragonfly_schematic.pdf")
fig.savefig(OUT / "dragonfly_schematic.svg")
fig.savefig(OUT / "dragonfly_schematic.png", dpi=300)
print("written to", OUT)
