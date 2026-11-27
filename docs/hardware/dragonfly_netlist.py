"""Dragonfly hardware netlist (Rev B): the single source of truth for the schematic.

Every component pin is listed with its electrical type and the net it connects
to. `check()` runs electrical rule checks; `export()` writes a netlist CSV,
a BOM CSV and a verification report. The schematic drawing script imports
NETS from here and refuses to render a net label that is not in this file.

Usage:  python dragonfly_netlist.py [outdir]
"""

import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

# Pin types (ERC):
#   PWR_OUT  supplies a rail          PWR_IN  needs a rail
#   OUT      drives a signal          IN      needs a driver
#   BIDIR    I/O (I2C SDA)            PAS     passive (R, C, switch, diode)
#   NC       intentionally unconnected
PWR_OUT, PWR_IN, OUT, IN, BIDIR, PAS, NC = "PWR_OUT", "PWR_IN", "OUT", "IN", "BIDIR", "PAS", "NC"

# Logic levels of each net, used for the voltage-domain check (volts, max).
GROUND = "GND"

# ---------------------------------------------------------------------- parts
# ref: (value, description, supplier part / procurement line, {pin: (name, type, net)})
PARTS = {
    "U1": (
        "ESP32-WROOM-32 DevKit",
        "Main controller, 38-pin DevKit",
        "Procurement #3",
        {
            "5V": ("5V (USB VBUS)", PWR_OUT, "+5V"),
            "3V3": ("3V3", PWR_OUT, "+3V3"),
            "GND": ("GND", PWR_OUT, GROUND),
            "IO36": ("GPIO36 / VP, ADC1_CH0", IN, "DOPPLER_ADC"),
            "IO16": ("GPIO16 / RX2", IN, "RD_TX"),
            "IO17": ("GPIO17 / TX2", OUT, "RD_RX"),
            "IO25": ("GPIO25", OUT, "PAN_PWM"),
            "IO26": ("GPIO26", OUT, "TILT_PWM"),
            "IO27": ("GPIO27", OUT, "LASER_EN"),
            "IO14": ("GPIO14 (INPUT_PULLUP)", IN, "ARM_SENSE"),
            "IO21": ("GPIO21 / SDA", BIDIR, "I2C_SDA"),
            "IO22": ("GPIO22 / SCL", OUT, "I2C_SCL"),
        },
    ),
    "M1": (
        "RD-03D",
        "Ai-Thinker 24 GHz FMCW radar, UART",
        "Procurement #1",
        {
            "5V": ("5V", PWR_IN, "+5V"),
            "GND": ("GND", PWR_IN, GROUND),
            "TX": ("TX", OUT, "M1_TX"),
            "RX": ("RX", IN, "M1_RX"),
        },
    ),
    "M2": (
        "CDM324",
        "24 GHz CW Doppler module, IF output",
        "Procurement #2",
        {
            "VCC": ("VCC", PWR_IN, "+5V"),
            "GND": ("GND", PWR_IN, GROUND),
            "IF": ("IF", OUT, "DOPPLER_IF"),
        },
    ),
    "U2": (
        "LM358",
        "Dual op-amp, Doppler amplifier stages 1 and 2",
        "Procurement #5",
        {
            "1": ("OUT A", OUT, "AMP1_OUT"),
            "2": ("-IN A", IN, "AMP1_FB"),
            "3": ("+IN A", IN, "AMP1_IN"),
            "4": ("GND", PWR_IN, GROUND),
            "5": ("+IN B", IN, "AMP1_OUT"),
            "6": ("-IN B", IN, "AMP2_FB"),
            "7": ("OUT B", OUT, "AMP2_OUT"),
            "8": ("V+", PWR_IN, "+5V"),
        },
    ),
    "U3": (
        "LM358",
        "Dual op-amp, VREF buffer (B unused, tied off)",
        "Procurement #5",
        {
            "1": ("OUT A", PWR_OUT, "VREF"),  # buffer output acts as the VREF rail source
            "2": ("-IN A", IN, "VREF"),
            "3": ("+IN A", IN, "VREF_DIV"),
            "4": ("GND", PWR_IN, GROUND),
            "5": ("+IN B", IN, "VREF"),
            "6": ("-IN B", IN, "U3B_FB"),
            "7": ("OUT B", OUT, "U3B_FB"),
            "8": ("V+", PWR_IN, "+5V"),
        },
    ),
    "J1": (
        "DC barrel jack",
        "Servo supply input, 5 V >= 5 A",
        "Procurement #10",
        {
            "+": ("+", PWR_OUT, "+5V_SERVO"),
            "-": ("-", PWR_OUT, GROUND),
        },
    ),
    "M3": (
        "MG996R",
        "Pan servo",
        "Procurement #9",
        {
            "SIG": ("SIG", IN, "PAN_PWM"),
            "V+": ("V+", PWR_IN, "+5V_SERVO"),
            "GND": ("GND", PWR_IN, GROUND),
        },
    ),
    "M4": (
        "MG996R",
        "Tilt servo",
        "Procurement #9",
        {
            "SIG": ("SIG", IN, "TILT_PWM"),
            "V+": ("V+", PWR_IN, "+5V_SERVO"),
            "GND": ("GND", PWR_IN, GROUND),
        },
    ),
    "S1": (
        "Key switch, 2-pole",
        "Laser arm switch: A breaks laser supply, B tells firmware",
        "Procurement #13",
        {
            "A1": ("A common", PAS, "+5V"),
            "A2": ("A out", PAS, "LASER_PWR"),
            "B1": ("B common", PAS, "ARM_SW"),
            "B2": ("B out", PAS, GROUND),
        },
    ),
    "M5": (
        "Laser 650 nm <= 1 mW",
        "IEC 60825-1 Class 2 laser module, 5 V",
        "Procurement #12",
        {"+": ("+", PWR_IN, "LASER_PWR"), "-": ("-", PAS, "LASER_SW")},
    ),
    "Q1": (
        "AO3400",
        "Logic-level N-MOSFET, low-side laser switch",
        "Procurement #14",
        {"G": ("G", IN, "LASER_GATE"), "D": ("D", PAS, "LASER_SW"), "S": ("S", PAS, GROUND)},
    ),
    "M6": (
        "SSD1306 OLED",
        '0.96" 128x64 I2C display, addr 0x3C',
        "Procurement #15",
        {
            "VCC": ("VCC", PWR_IN, "+3V3"),
            "GND": ("GND", PWR_IN, GROUND),
            "SCL": ("SCL", IN, "I2C_SCL"),
            "SDA": ("SDA", BIDIR, "I2C_SDA"),
        },
    ),
    "D1": (
        "BAT54S",
        "Dual Schottky, ADC input clamp",
        "Procurement #6 (add)",
        {"1": ("A1", PAS, GROUND), "2": ("K2", PAS, "+3V3"), "3": ("K1/A2", PAS, "DOPPLER_ADC")},
    ),
    "RV1": (
        "10 kΩ trimmer",
        "Stage 2 gain trim, wired as rheostat",
        "Procurement #6",
        {"1": ("1", PAS, "AMP2_RV"), "2": ("wiper", PAS, "AMP2_OUT"), "3": ("3", PAS, "AMP2_OUT")},
    ),
}

# Two-terminal passives: ref: (value, description, net1, net2)
PASSIVES = {
    "R1": ("100 kΩ", "Stage 1 input bias to VREF", "AMP1_IN", "VREF"),
    "R2": ("1 kΩ", "Stage 1 gain resistor", "AMP1_FB", "AMP1_RG"),
    "R3": ("100 kΩ", "Stage 1 feedback", "AMP1_FB", "AMP1_OUT"),
    "R4": ("470 Ω", "Stage 2 gain resistor", "AMP2_FB", "AMP2_RG"),
    "R5": ("10 kΩ", "Stage 2 feedback, fixed part", "AMP2_FB", "AMP2_RV"),
    "R6": ("10 kΩ", "Anti-alias low-pass and clamp current limit", "AMP2_OUT", "DOPPLER_ADC"),
    "R7": ("10 kΩ", "VREF divider, top", "+3V3", "VREF_DIV"),
    "R8": ("10 kΩ", "VREF divider, bottom", "VREF_DIV", GROUND),
    "R9": ("100 Ω", "Q1 gate series resistor", "LASER_EN", "LASER_GATE"),
    "R10": ("10 kΩ", "Q1 gate pull-down (laser off while U1 resets)", "LASER_GATE", GROUND),
    "R11": ("1 kΩ", "GPIO14 series protection (pin toggles at boot)", "ARM_SENSE", "ARM_SW"),
    "R12": ("100 Ω", "RD-03D TX series resistor (datasheet 7.4)", "M1_TX", "RD_TX"),
    "R13": ("100 Ω", "RD-03D RX series resistor (datasheet 7.4)", "RD_RX", "M1_RX"),
    "C1": ("1000 µF 10 V", "Servo rail bulk, at J1 (electrolytic)", "+5V_SERVO", GROUND),
    "C2": ("1000 µF 10 V", "Servo rail bulk, at servos (electrolytic)", "+5V_SERVO", GROUND),
    "C3": ("100 nF", "IF input coupling", "DOPPLER_IF", "AMP1_IN"),
    "C4": ("1 nF", "Stage 1 low-pass", "AMP1_FB", "AMP1_OUT"),
    "C5": ("10 µF", "Stage 1 DC block, ceramic X5R", "AMP1_RG", "VREF"),
    "C6": ("4.7 nF", "Stage 2 low-pass", "AMP2_FB", "AMP2_OUT"),
    "C7": ("22 µF", "Stage 2 DC block, ceramic X5R", "AMP2_RG", "VREF"),
    "C8": ("10 nF", "Anti-alias low-pass", "DOPPLER_ADC", GROUND),
    "C9": ("10 µF", "VREF divider filter", "VREF_DIV", GROUND),
    "C10": ("100 nF", "U2 decoupling", "+5V", GROUND),
    "C11": ("100 nF", "U3 decoupling", "+5V", GROUND),
    "C12": ("10 µF", "RD-03D supply bulk, ceramic X5R (ripple ≤ 100 mV)", "+5V", GROUND),
}
POLARISED = {"C1": ("+5V_SERVO", GROUND), "C2": ("+5V_SERVO", GROUND)}  # (+, -)

# Nets that leave the sheet on purpose (none). USB to the host is inside U1.
RAILS = {"+5V": 5.0, "+5V_SERVO": 5.0, "+3V3": 3.3, "VREF": 1.65, GROUND: 0.0}


def connections():
    nets = defaultdict(list)
    for ref, (_, _, _, pins) in PARTS.items():
        for pin, (name, ptype, net) in pins.items():
            nets[net].append((ref, pin, name, ptype))
    for ref, (_, _, n1, n2) in PASSIVES.items():
        nets[n1].append((ref, "1", "1", PAS))
        nets[n2].append((ref, "2", "2", PAS))
    return dict(nets)


NETS = connections()


# ---------------------------------------------------------------------- checks
def values():
    def parse(v):
        m = re.match(r"([\d.]+)\s*([pnµukM]?)", v)
        mult = {"p": 1e-12, "n": 1e-9, "µ": 1e-6, "u": 1e-6, "k": 1e3, "M": 1e6, "": 1}[m.group(2)]
        return float(m.group(1)) * mult

    return {ref: parse(v[0]) for ref, v in PASSIVES.items()}


def check(board_hpp=None):
    """Return (results, ok). results: list of (status, check, detail)."""
    res = []

    def add(ok, name, detail):
        res.append(("PASS" if ok else "FAIL", name, detail))

    # 1. every net has at least two connections
    single = [n for n, c in NETS.items() if len(c) < 2]
    add(not single, "No single-pin nets", f"{len(NETS)} nets; dangling: {single or 'none'}")

    # 2. every pin is assigned (no unconnected pins except NC)
    unassigned = [
        (r, p)
        for r, (_, _, _, pins) in PARTS.items()
        for p, (_, t, n) in pins.items()
        if not n and t != NC
    ]
    add(not unassigned, "Every pin connected", f"unconnected: {unassigned or 'none'}")

    # 3. at most one driver per signal net (ground and rails exempt)
    multi = []
    for n, c in NETS.items():
        drivers = [f"{r}.{p}" for r, p, _, t in c if t in (OUT, PWR_OUT)]
        if n != GROUND and len(drivers) > 1:
            multi.append((n, drivers))
    add(not multi, "One driver per net", f"conflicts: {multi or 'none'}")

    # 4/5. every input and supply pin reaches a source, directly or through one passive
    #      (resistors, switch poles, trimmer). Capacitors do not carry DC; GND is not a driver here.
    links = defaultdict(set)
    for r, (_val, _, n1, n2) in PASSIVES.items():
        if r.startswith("R"):
            links[n1].add((r, n2))
            links[n2].add((r, n1))
    for r, a, b in (("S1", "A1", "A2"), ("S1", "B1", "B2"), ("RV1", "1", "3")):
        n1, n2 = PARTS[r][3][a][2], PARTS[r][3][b][2]
        links[n1].add((r, n2))
        links[n2].add((r, n1))

    def sourced(n, kinds):
        return any(t in kinds for *_, t in NETS[n])

    undriven, via = [], []
    for n, c in NETS.items():
        types = {t for *_, t in c}
        if types & {IN} and not types & {OUT, PWR_OUT, BIDIR}:
            hop, seen, todo = [], {n}, [(n, [])]
            while todo:  # breadth-first through resistive parts
                cur, path = todo.pop(0)
                for r, m in links[cur]:
                    if m in seen or m == GROUND:
                        continue
                    seen.add(m)
                    if sourced(m, {OUT, PWR_OUT, BIDIR}):
                        hop.append(("+".join(path + [r]), m))
                    else:
                        todo.append((m, path + [r]))
            if n == "ARM_SENSE":
                hop.append(("U1", "internal pull-up"))
            (via if hop else undriven).append((n, hop))
    add(
        not undriven,
        "Every input has a DC path to a driver",
        "; ".join(f"{n} via {', '.join(f'{r}→{m}' for r, m in h)}" for n, h in via)
        + f"; undriven: {undriven or 'none'}",
    )
    bad = []
    for n, c in NETS.items():
        if any(t == PWR_IN for *_, t in c) and not sourced(n, {PWR_OUT}):
            if not any(sourced(m, {PWR_OUT}) for _, m in links[n]):
                bad.append(n)
    add(
        not bad,
        "Every supply pin has a source",
        f"LASER_PWR fed from +5V through S1A; missing: {bad or 'none'}",
    )

    # 6. ESP32 pins carry no more than 3.3 V
    esp_nets = {n for _, _, n in PARTS["U1"][3].values()} - {"+5V", "+3V3", GROUND}
    hot = [n for n in esp_nets if RAILS.get(n, 0) > 3.3]
    add(
        not hot,
        "ESP32 GPIOs stay within 3.3 V",
        "RD-03D UART is 3.3 V logic; servo SIG and Q1 gate are inputs; DOPPLER_ADC clamped by D1 to +3V3 "
        f"via R6; over-voltage nets: {hot or 'none'}",
    )

    # 7. ADC on ADC1 (ADC2 unusable with Wi-Fi)
    add(PARTS["U1"][3]["IO36"][2] == "DOPPLER_ADC", "Doppler ADC on ADC1", "GPIO36 = ADC1_CH0")

    # 8. no strapping pins used as outputs that could upset boot (0, 2, 5, 12, 15)
    strap = {"IO0", "IO2", "IO5", "IO12", "IO15"} & set(PARTS["U1"][3])
    add(not strap, "No ESP32 strapping pins used", f"used: {sorted(strap) or 'none'}")

    # 9. polarised caps the right way round
    okpol = all(PASSIVES[r][2] == p and PASSIVES[r][3] == m for r, (p, m) in POLARISED.items())
    add(okpol, "Electrolytic polarity", "C1, C2: + on +5V_SERVO, - on GND")

    # 10. laser hardware interlock: laser supply only through S1A
    lp = {(r, p) for r, p, *_ in NETS["LASER_PWR"]}
    add(
        lp == {("S1", "A2"), ("M5", "+")},
        "Laser powered only through S1A",
        f"LASER_PWR = {sorted(lp)}",
    )
    add(
        any(r == "R10" for r, *_ in NETS["LASER_GATE"]),
        "Q1 gate pulled down",
        "R10 holds Q1 off while U1 boots",
    )

    # 10b. GPIO14 drives a PWM burst at boot; it must not meet the closed switch directly
    direct = {r for r, *_ in NETS["ARM_SENSE"]} - {"U1"}
    add(
        direct == {"R11"},
        "GPIO14 protected from the arm switch",
        "GPIO14 toggles during boot; R11 limits the current if S1B is closed "
        f"(ARM_SENSE also connects to: {sorted(direct)})",
    )
    # 10c. RD-03D datasheet 7.4: 10 to 100 Ω in series with the UART lines
    rd = all(
        any(r in ("R12", "R13") for r, *_ in NETS[n]) for n in ("RD_TX", "RD_RX", "M1_TX", "M1_RX")
    )
    add(rd, "RD-03D UART series resistors", "R12, R13 = 100 Ω (Rd-03D spec V1.0.0, section 7.4)")

    # 11. servo current kept off the USB rail
    sv = {r for r, *_ in NETS["+5V_SERVO"]}
    add(
        sv == {"J1", "M3", "M4", "C1", "C2"},
        "Servos on separate supply",
        f"+5V_SERVO = {sorted(sv)}",
    )

    # 12. firmware pin map matches board.hpp
    if board_hpp and Path(board_hpp).exists():
        src = Path(board_hpp).read_text()
        want = {
            "kRadarRxPin": ("IO16", "RD_TX"),
            "kRadarTxPin": ("IO17", "RD_RX"),
            "kDopplerAdcPin": ("IO36", "DOPPLER_ADC"),
            "kPanServoPin": ("IO25", "PAN_PWM"),
            "kTiltServoPin": ("IO26", "TILT_PWM"),
            "kLaserEnablePin": ("IO27", "LASER_EN"),
            "kArmSwitchPin": ("IO14", "ARM_SENSE"),
        }
        mism = []
        for const, (pin, net) in want.items():
            m = re.search(rf"{const}\s*=\s*(\d+)", src)
            if not m or f"IO{m.group(1)}" != pin or PARTS["U1"][3][pin][2] != net:
                mism.append(const)
        add(
            not mism,
            "Pin map matches firmware/src/board.hpp",
            f"{len(want)} pins compared; mismatches: {mism or 'none'}",
        )

    # 13. analog front end numbers
    v = values()
    g1 = 1 + v["R3"] / v["R2"]
    g2lo, g2hi = 1 + v["R5"] / v["R4"], 1 + (v["R5"] + 10e3) / v["R4"]
    hp = {
        k: 1 / (2 * math.pi * a * b)
        for k, (a, b) in {
            "R1·C3": (v["R1"], v["C3"]),
            "R2·C5": (v["R2"], v["C5"]),
            "R4·C7": (v["R4"], v["C7"]),
        }.items()
    }
    lp = {
        k: 1 / (2 * math.pi * a * b)
        for k, (a, b) in {"R3·C4": (v["R3"], v["C4"]), "R6·C8": (v["R6"], v["C8"])}.items()
    }
    lp2 = (1 / (2 * math.pi * (v["R5"] + 10e3) * v["C6"]), 1 / (2 * math.pi * v["R5"] * v["C6"]))
    fd = 2 * 24.125e9 / 299792458  # Hz per m/s
    gbw_need = g1 * max(lp.values())
    res.append(("INFO", "Stage 1 gain", f"1 + R3/R2 = {g1:.0f} ({20 * math.log10(g1):.1f} dB)"))
    res.append(
        (
            "INFO",
            "Stage 2 gain",
            f"1 + (R5+RV1)/R4 = {g2lo:.0f} to {g2hi:.0f} "
            f"({20 * math.log10(g2lo):.1f} to {20 * math.log10(g2hi):.1f} dB)",
        )
    )
    res.append(("INFO", "High-pass corners", ", ".join(f"{k} = {f:.1f} Hz" for k, f in hp.items())))
    res.append(
        (
            "INFO",
            "Low-pass corners",
            ", ".join(f"{k} = {f:.0f} Hz" for k, f in lp.items())
            + f", (R5+RV1)·C6 = {lp2[0]:.0f} to {lp2[1]:.0f} Hz",
        )
    )
    res.append(
        (
            "INFO",
            "Doppler scale",
            f"2·f0/c = {fd:.0f} Hz per m/s at 24.125 GHz: 0.2 m/s = {0.2 * fd:.0f} Hz, "
            f"5 m/s = {5 * fd:.0f} Hz",
        )
    )
    add(
        max(hp.values()) < 0.2 * fd and min(lp.values()) > 5 * fd,
        "Target speeds inside passband",
        f"0.2 to 5 m/s maps to {0.2 * fd:.0f} to {5 * fd:.0f} Hz; "
        f"passband ≈ {max(hp.values()):.0f} Hz to {min(lp.values()):.0f} Hz",
    )
    add(
        gbw_need < 1e6,
        "LM358 bandwidth sufficient",
        f"stage 1 needs ≈ {gbw_need / 1e3:.0f} kHz GBW; LM358 ≈ 1 MHz",
    )
    vref = 3.3 * v["R8"] / (v["R7"] + v["R8"])
    add(
        abs(vref - 1.65) < 0.01 and vref < 5 - 1.5,
        "VREF inside LM358 input range",
        f"VREF = {vref:.2f} V; LM358 common-mode limit at 5 V ≈ 3.5 V",
    )
    res.append(
        (
            "INFO",
            "ADC headroom",
            "LM358 swings ≈ 0 to 3.5 V on 5 V; D1 + R6 clamp to ≤ 3.3 V + 0.3 V. "
            "ESP32 ADC at 11 dB is most linear ≈ 0.15 to 2.45 V, so set RV1 for ≤ ±0.8 V around VREF.",
        )
    )

    # 14. USB (+5V) current budget. Figures are datasheet or typical values (mA, avg / peak).
    budget = {
        "U1 ESP32 (Wi-Fi TX peak 240 mA, ESP32 datasheet)": (80, 240),
        "M1 RD-03D (avg 92 mA, peak ≥ 200 mA, Rd-03D spec Table 4 and 7.3)": (92, 200),
        "M2 CDM324 (≈ 40 mA, supplier listing)": (40, 40),
        "M5 laser module (≤ 1 mW modules draw ≈ 20 to 30 mA; check yours)": (30, 30),
        "M6 SSD1306 OLED (≈ 20 mA all pixels on)": (10, 20),
        "U2, U3 LM358 (≈ 0.7 mA each)": (2, 2),
    }
    avg = sum(a for a, _ in budget.values())
    peak = sum(b for _, b in budget.values())
    res.append(
        (
            "INFO",
            "USB 5 V budget",
            f"≈ {avg} mA average, ≈ {peak} mA worst-case peak: "
            + "; ".join(f"{k}: {a}/{b}" for k, (a, b) in budget.items()),
        )
    )
    res.append(
        (
            "PASS" if avg < 500 else "FAIL",
            "Average load inside a 500 mA USB 2.0 port",
            f"{avg} mA. Peaks can reach ≈ {peak} mA, so use a USB 3 port (900 mA) or a "
            "≥ 1 A USB supply if the board browns out",
        )
    )

    ok = all(s != "FAIL" for s, *_ in res)
    return res, ok


# ---------------------------------------------------------------------- export
def export(outdir, board_hpp=None):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "dragonfly_netlist.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Net", "Ref", "Pin", "Pin name", "Pin type"])
        for n in sorted(NETS):
            for r, p, name, t in sorted(NETS[n]):
                w.writerow([n, r, p, name, t])
    rows = []
    for r, (val, desc, src, _) in PARTS.items():
        rows.append((r, val, desc, src))
    for r, (val, desc, *_) in PASSIVES.items():
        rows.append((r, val, desc, "Procurement #11" if r in ("C1", "C2") else "Procurement #6"))

    def key(row):
        ref = row[0]
        return re.sub(r"\d+", "", ref), int(re.sub(r"\D+", "", ref))

    with open(out / "dragonfly_bom.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Ref", "Value", "Function", "Source"])
        for row in sorted(rows, key=key):
            w.writerow(row)
    res, ok = check(board_hpp)
    return res, ok


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    hpp = sys.argv[2] if len(sys.argv) > 2 else None
    res, ok = export(outdir, hpp)
    for s, n, d in res:
        print(f"[{s}] {n}: {d}")
    print("ALL CHECKS PASS" if ok else "CHECKS FAILED")
    sys.exit(0 if ok else 1)
