"""
Atom1 / SS1 Investor Demo Simulator - 20T/28T, 50 cadence
Python 3 standard library only (tkinter)

Investor-oriented GUI version:
- Dark dashboard layout
- Large KPI cards for speed, mode, torque margin, RPM
- Actual motor RPM can rise under low-load surplus conditions, with softened flat-road overspeed behavior
- Current map table with active cell: ▶ [ value ] ◀ in bold blue
- Right-top compact visual hero panel added above controls (as requested)
- Visual torque bars and automatic mode switching
- 20T chainring / 28T rear sprocket
- 85kg required torque table including 6Nm flat-road baseline
"""

import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Dict, List, Tuple
import math

# -------------------------
# Model constants
# -------------------------
MOTOR_STEPS: List[int] = [0, 640, 960, 1280, 1600, 1750]
DRIVE_MODES: List[str] = ["A", "B", "C", "D", "E", "F"]  # high current -> low current
DEFAULT_MODE = "E"
BOOST_MODE = "X"
MAX_MOTOR_RPM = 2000.0

CURRENT_MAP: Dict[str, Dict[int, float]] = {
    "A": {0: 0.0, 640: 6.94, 960: 6.94, 1280: 6.94, 1600: 6.94, 1750: 6.94},
    "B": {0: 0.0, 640: 6.94, 960: 6.94, 1280: 6.00, 1600: 5.00, 1750: 5.00},
    "C": {0: 0.0, 640: 6.94, 960: 6.00, 1280: 5.00, 1600: 4.00, 1750: 4.00},
    "D": {0: 0.0, 640: 6.94, 960: 5.00, 1280: 4.00, 1600: 3.00, 1750: 3.00},
    "E": {0: 0.0, 640: 6.94, 960: 4.00, 1280: 3.00, 1600: 2.00, 1750: 2.00},
    "F": {0: 0.0, 640: 4.00, 960: 3.00, 1280: 2.00, 1600: 1.50, 1750: 1.00},
    "X": {0: 0.0, 640: 14.00, 960: 14.00, 1280: 14.00, 1600: 14.00, 1750: 14.00},
}

WORM_EFFICIENCY = {0: 0.0, 640: 0.68, 960: 0.70, 1280: 0.75, 1600: 0.78, 1750: 0.80}
KT_NM_PER_A = 0.196
WORM_REDUCTION = 32.0
CHAINRING_TEETH = 20.0
REAR_SPROCKET_TEETH = 28.0
WHEEL_DIAMETER_M = 0.508  # 20 inch
WHEEL_CIRCUMFERENCE_M = math.pi * WHEEL_DIAMETER_M
CADENCE_RPM = 50.0
RIDER_TORQUE_NM = 6.0

REQUIRED_TORQUE_BY_SLOPE_85KG: Dict[float, float] = {
    0: 6.00,
    1: 7.12,
    2: 9.24,
    3: 11.35,
    4: 13.47,
    5: 15.59,
    6: 17.71,
    7: 19.83,
    8: 21.94,
    9: 24.06,
    10: 26.18,
    11: 28.30,
    12: 30.42,
    13: 32.53,
    14: 34.65,
    15: 36.77,
}

# -------------------------
# Utility and model functions
# -------------------------
def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def interp(x: float, points: Dict[float, float]) -> float:
    xs = sorted(points.keys())
    if x <= xs[0]:
        return points[xs[0]]
    if x >= xs[-1]:
        return points[xs[-1]]
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return points[x0] + t * (points[x1] - points[x0])
    return points[xs[-1]]


def required_torque_85kg(grade_percent: float) -> float:
    return interp(grade_percent, REQUIRED_TORQUE_BY_SLOPE_85KG)


def ring_rpm(motor_rpm: float) -> float:
    return motor_rpm / WORM_REDUCTION


def chainring_rpm(cadence_rpm: float, motor_rpm: float) -> float:
    return 3.0 * cadence_rpm + 2.0 * ring_rpm(motor_rpm)


def wheel_rpm(cadence_rpm: float, motor_rpm: float) -> float:
    return chainring_rpm(cadence_rpm, motor_rpm) * (CHAINRING_TEETH / REAR_SPROCKET_TEETH)


def speed_kmh(wheel_rpm_value: float) -> float:
    return wheel_rpm_value * WHEEL_CIRCUMFERENCE_M * 60.0 / 1000.0


def motor_torque_at_ring(mode: str, motor_rpm: int) -> float:
    current = CURRENT_MAP[mode][motor_rpm]
    return KT_NM_PER_A * current * WORM_REDUCTION * WORM_EFFICIENCY[motor_rpm]


def motor_torque_at_wheel(mode: str, motor_rpm: int, cadence_rpm: float = CADENCE_RPM) -> float:
    if motor_rpm == 0:
        return 0.0
    wrpm = wheel_rpm(cadence_rpm, motor_rpm)
    rrpm = ring_rpm(motor_rpm)
    if wrpm <= 0:
        return 0.0
    return motor_torque_at_ring(mode, motor_rpm) * rrpm / wrpm


def current_text(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))} A"
    return f"{value:.2f} A".replace(".00", "")


def step_mode_up(mode: str) -> str:
    if mode == BOOST_MODE:
        return BOOST_MODE
    idx = DRIVE_MODES.index(mode)
    return DRIVE_MODES[max(0, idx - 1)]


def step_mode_down(mode: str) -> str:
    if mode == BOOST_MODE:
        return DEFAULT_MODE
    idx = DRIVE_MODES.index(mode)
    return DRIVE_MODES[min(len(DRIVE_MODES) - 1, idx + 1)]


@dataclass
class SimState:
    motor_index: int = 0
    mode: str = DEFAULT_MODE
    boost_ticks: int = 0
    surplus_seconds: float = 0.0
    speed_limit_kmh: float = 25.0
    speed_limit_enabled: bool = False

    @property
    def target_motor_rpm(self) -> int:
        rpm = MOTOR_STEPS[self.motor_index]
        if self.speed_limit_enabled and rpm > 0:
            projected_speed = speed_kmh(wheel_rpm(CADENCE_RPM, rpm))
            if projected_speed >= self.speed_limit_kmh:
                rpm = max(0, rpm - 300)
                rpm = min(MOTOR_STEPS, key=lambda s: abs(s - rpm))
        return rpm


class KPI(tk.Frame):
    def __init__(self, master, title, unit="", accent="#38BDF8"):
        super().__init__(master, bg="#111827", highlightbackground="#243244", highlightthickness=1)
        self.title_label = tk.Label(self, text=title, bg="#111827", fg="#9CA3AF", font=("Segoe UI", 10, "bold"))
        self.title_label.pack(anchor="w", padx=14, pady=(10, 0))
        self.value_label = tk.Label(self, text="-", bg="#111827", fg="white", font=("Segoe UI", 24, "bold"))
        self.value_label.pack(anchor="w", padx=14, pady=(0, 2))
        self.unit_label = tk.Label(self, text=unit, bg="#111827", fg=accent, font=("Segoe UI", 10, "bold"))
        self.unit_label.pack(anchor="w", padx=14, pady=(0, 10))

    def set_value(self, value, unit=None, good=None):
        self.value_label.config(text=value)
        if unit is not None:
            self.unit_label.config(text=unit)
        if good is None:
            self.value_label.config(fg="white")
        elif good:
            self.value_label.config(fg="#86EFAC")
        else:
            self.value_label.config(fg="#FCA5A5")


class InvestorDemo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Atom1 / SS1 Investor Demo - 20T/28T")
        self.geometry("1320x860")
        self.minsize(1180, 780)
        self.configure(bg="#0B1020")

        self.state_data = SimState()
        self.grade = tk.DoubleVar(value=5.0)
        self.speed_limit = tk.DoubleVar(value=25.0)
        self.status = tk.StringVar(value="READY · Default mode E · Press UP to start the SS1 RPM-domain drive demo")
        self.values: Dict[str, tk.StringVar] = {k: tk.StringVar(value="-") for k in [
            "mode", "target_rpm", "actual_rpm", "current", "cadence", "ring", "chainring", "wheel",
            "speed", "ring_torque", "motor_torque", "rider_torque", "available_torque", "required_torque",
            "margin", "decision"
        ]}
        self.table_cells: Dict[Tuple[int, str], tk.Label] = {}
        self.rpm_labels: Dict[int, tk.Label] = {}
        self.mode_headers: Dict[str, tk.Label] = {}
        self.kpis: Dict[str, KPI] = {}
        self._setup_styles()
        self._build_ui()
        self._update_loop()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0B1020")
        style.configure("Panel.TFrame", background="#111827")
        style.configure("TLabel", background="#0B1020", foreground="#E5E7EB", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#111827", foreground="#E5E7EB", font=("Segoe UI", 10))
        style.configure("Demo.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8), foreground="white", background="#2563EB")
        style.map("Demo.TButton", background=[("active", "#1D4ED8")])
        style.configure("Ghost.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8), foreground="#E5E7EB", background="#1F2937")
        style.map("Ghost.TButton", background=[("active", "#374151")])
        style.configure("Horizontal.TScale", background="#111827", troughcolor="#1F2937")
        style.configure("Dark.TCheckbutton", background="#111827", foreground="#E5E7EB", font=("Segoe UI", 10, "bold"))

    def _panel(self, master):
        return tk.Frame(master, bg="#111827", highlightbackground="#243244", highlightthickness=1)

    def _build_ui(self):
        header = tk.Frame(self, bg="#0B1020")
        header.pack(fill="x", padx=20, pady=(16, 8))

        left_header = tk.Frame(header, bg="#0B1020")
        left_header.pack(side="left", fill="x", expand=True)
        tk.Label(left_header, text="ATOM1 · SS1 INVESTOR DEMO", bg="#0B1020", fg="#38BDF8", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(left_header, text="RPM-domain drivetrain control for compact urban e-bikes", bg="#0B1020", fg="white", font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(left_header, text="20T / 28T · 50 cadence · 85kg load model · F640=4A · actual RPM cap 2000", bg="#0B1020", fg="#9CA3AF", font=("Segoe UI", 11)).pack(anchor="w")

        badge = tk.Frame(header, bg="#172554", highlightbackground="#2563EB", highlightthickness=1)
        badge.pack(side="right", padx=10)
        tk.Label(badge, text="SS1", bg="#172554", fg="#93C5FD", font=("Segoe UI", 11, "bold")).pack(padx=18, pady=(10, 0))
        tk.Label(badge, text="e-CVT concept", bg="#172554", fg="white", font=("Segoe UI", 16, "bold")).pack(padx=18, pady=(0, 10))

        controls = tk.Frame(self, bg="#0B1020")
        controls.pack(fill="x", padx=20, pady=8)
        ttk.Button(controls, text="⟲ Reset", style="Ghost.TButton", command=self.reset).pack(side="left", padx=4)
        ttk.Button(controls, text="▲ UP  Motor RPM", style="Demo.TButton", command=self.motor_up).pack(side="left", padx=4)
        ttk.Button(controls, text="▼ DOWN  Motor RPM", style="Ghost.TButton", command=self.motor_down).pack(side="left", padx=4)
        ttk.Button(controls, text="⚡ X Boost 14A", style="Demo.TButton", command=self.boost).pack(side="left", padx=4)
        ttk.Button(controls, text="Mode + Current", style="Ghost.TButton", command=self.manual_mode_up).pack(side="left", padx=4)
        ttk.Button(controls, text="Mode - Current", style="Ghost.TButton", command=self.manual_mode_down).pack(side="left", padx=4)

        body = tk.Frame(self, bg="#0B1020")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        left = tk.Frame(body, bg="#0B1020")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = tk.Frame(body, bg="#0B1020", width=520)
        right.pack(side="right", fill="both", padx=(10, 0))

        kpi_grid = tk.Frame(left, bg="#0B1020")
        kpi_grid.pack(fill="x")
        for i in range(4):
            kpi_grid.columnconfigure(i, weight=1)
        specs = [
            ("speed", "Speed", "km/h", "#38BDF8"),
            ("mode", "Drive Mode", "ABCDEF/X", "#A78BFA"),
            ("margin", "Torque Margin", "Nm", "#34D399"),
            ("rpm", "Motor RPM", "target / actual · max 2000", "#FBBF24"),
        ]
        for i, (key, title, unit, accent) in enumerate(specs):
            card = KPI(kpi_grid, title, unit, accent)
            card.grid(row=0, column=i, sticky="nsew", padx=5, pady=5)
            self.kpis[key] = card

        mid = tk.Frame(left, bg="#0B1020")
        mid.pack(fill="both", expand=True, pady=(8, 0))
        visual = self._panel(mid)
        visual.pack(side="left", fill="both", expand=True, padx=(0, 8))
        details = self._panel(mid)
        details.pack(side="right", fill="both", expand=True, padx=(8, 0))

        tk.Label(visual, text="Torque & control response", bg="#111827", fg="white", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
        self.canvas = tk.Canvas(visual, bg="#111827", highlightthickness=0, height=330)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(details, text="Live drivetrain telemetry", bg="#111827", fg="white", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        rows = [
            ("Target motor RPM", "target_rpm"), ("Actual motor RPM", "actual_rpm"), ("Mapped current", "current"),
            ("Cadence / carrier", "cadence"), ("Ring gear RPM", "ring"), ("Chainring / sun RPM", "chainring"),
            ("Wheel RPM", "wheel"), ("Ring gear torque", "ring_torque"), ("Motor wheel torque", "motor_torque"),
            ("Rider wheel torque", "rider_torque"), ("Available torque", "available_torque"), ("Required torque", "required_torque"),
            ("Controller decision", "decision"),
        ]
        grid = tk.Frame(details, bg="#111827")
        grid.pack(fill="both", expand=True, padx=16, pady=6)
        for r, (label, key) in enumerate(rows):
            tk.Label(grid, text=label, bg="#111827", fg="#9CA3AF", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w", pady=4)
            tk.Label(grid, textvariable=self.values[key], bg="#111827", fg="#F9FAFB", font=("Consolas", 10, "bold"), wraplength=260, justify="left").grid(row=r, column=1, sticky="w", padx=(12, 0), pady=4)
        grid.columnconfigure(1, weight=1)

        # Right side top compact hero panel added as requested
        hero_panel = self._panel(right)
        hero_panel.pack(fill="x", pady=(0, 10))
        top_row = tk.Frame(hero_panel, bg="#111827")
        top_row.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(top_row, text="Dynamic drive preview", bg="#111827", fg="white", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.hero_mode_badge = tk.Label(top_row, text="Mode E", bg="#12335F", fg="#BFDBFE", font=("Segoe UI", 10, "bold"), padx=10, pady=4)
        self.hero_mode_badge.pack(side="right")
        self.hero_canvas = tk.Canvas(hero_panel, bg="#0A0F1E", highlightthickness=0, height=150)
        self.hero_canvas.pack(fill="x", padx=10, pady=(0, 10))

        load_panel = self._panel(right)
        load_panel.pack(fill="x", pady=(0, 10))
        tk.Label(load_panel, text="Demo controls", bg="#111827", fg="white", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        ctrl_inner = tk.Frame(load_panel, bg="#111827")
        ctrl_inner.pack(fill="x", padx=16, pady=(4, 14))
        tk.Label(ctrl_inner, text="Slope / grade", bg="#111827", fg="#9CA3AF", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.grade_label = tk.Label(ctrl_inner, text="5.0%", bg="#111827", fg="#38BDF8", font=("Segoe UI", 12, "bold"))
        self.grade_label.grid(row=0, column=1, sticky="e")
        ttk.Scale(ctrl_inner, from_=0, to=15, variable=self.grade, orient="horizontal", length=360).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        tk.Label(ctrl_inner, text="Speed limit", bg="#111827", fg="#9CA3AF", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w")
        self.limit_label = tk.Label(ctrl_inner, text="25.0 km/h", bg="#111827", fg="#38BDF8", font=("Segoe UI", 12, "bold"))
        self.limit_label.grid(row=2, column=1, sticky="e")
        ttk.Scale(ctrl_inner, from_=8, to=25, variable=self.speed_limit, orient="horizontal", length=360).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        self.limit_btn = ttk.Checkbutton(ctrl_inner, text="Use speed limit logic", style="Dark.TCheckbutton", command=self.toggle_speed_limit)
        self.limit_btn.grid(row=4, column=0, columnspan=2, sticky="w")
        ctrl_inner.columnconfigure(0, weight=1)

        map_panel = self._panel(right)
        map_panel.pack(fill="both", expand=True)
        tk.Label(map_panel, text="Current map table", bg="#111827", fg="white", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        self._build_current_map_grid(map_panel)
        tk.Label(map_panel, text="Active cell: ▶ [ value ] ◀  · bold blue highlight", bg="#111827", fg="#93C5FD", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(4, 12))

        status_bar = tk.Frame(self, bg="#020617")
        status_bar.pack(fill="x", side="bottom")
        tk.Label(status_bar, textvariable=self.status, bg="#020617", fg="#BFDBFE", font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=20, pady=8)

    def _build_current_map_grid(self, parent):
        grid = tk.Frame(parent, bg="#374151")
        grid.pack(fill="both", expand=True, padx=16, pady=8)
        headers = ["RPM", "A", "B", "C", "D", "E", "F", "X"]
        for c, h in enumerate(headers):
            lbl = tk.Label(grid, text=h, bg="#020617", fg="#E5E7EB", font=("Segoe UI", 9, "bold"), width=9, height=2)
            lbl.grid(row=0, column=c, sticky="nsew", padx=1, pady=1)
            if h in ["A", "B", "C", "D", "E", "F", "X"]:
                self.mode_headers[h] = lbl
        for r, rpm in enumerate(MOTOR_STEPS[1:], start=1):
            rpm_lbl = tk.Label(grid, text=str(rpm), bg="#1F2937", fg="#F9FAFB", font=("Segoe UI", 9, "bold"), width=9, height=2)
            rpm_lbl.grid(row=r, column=0, sticky="nsew", padx=1, pady=1)
            self.rpm_labels[rpm] = rpm_lbl
            for c, mode in enumerate(["A", "B", "C", "D", "E", "F", "X"], start=1):
                val = current_text(CURRENT_MAP[mode][rpm])
                cell = tk.Label(grid, text=val, bg="#111827", fg="#D1D5DB", font=("Segoe UI", 9), width=9, height=2)
                cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
                self.table_cells[(rpm, mode)] = cell
        for c in range(len(headers)):
            grid.columnconfigure(c, weight=1)
        for r in range(len(MOTOR_STEPS)):
            grid.rowconfigure(r, weight=1)
        self._refresh_table()

    def _refresh_table(self):
        active_rpm = self.state_data.target_motor_rpm
        active_mode = self.state_data.mode
        for mode, hdr in self.mode_headers.items():
            if mode == active_mode:
                hdr.config(bg="#DBEAFE", fg="#0B57D0", font=("Segoe UI", 10, "bold"))
            else:
                hdr.config(bg="#020617", fg="#E5E7EB", font=("Segoe UI", 9, "bold"))
        for rpm, rpm_lbl in self.rpm_labels.items():
            if rpm == active_rpm:
                rpm_lbl.config(bg="#DBEAFE", fg="#0B57D0", font=("Segoe UI", 10, "bold"), text=f"▶ {rpm}")
            else:
                rpm_lbl.config(bg="#1F2937", fg="#F9FAFB", font=("Segoe UI", 9, "bold"), text=str(rpm))
        for (rpm, mode), cell in self.table_cells.items():
            val = current_text(CURRENT_MAP[mode][rpm])
            if rpm == active_rpm and mode == active_mode:
                cell.config(text=f"▶ [ {val} ] ◀", bg="#E0F2FE", fg="#0B57D0", font=("Segoe UI", 11, "bold"))
            elif rpm == active_rpm:
                cell.config(text=val, bg="#172554", fg="#93C5FD", font=("Segoe UI", 9, "bold"))
            elif mode == active_mode:
                cell.config(text=val, bg="#0F172A", fg="#60A5FA", font=("Segoe UI", 9, "bold"))
            else:
                cell.config(text=val, bg="#111827", fg="#D1D5DB", font=("Segoe UI", 9))

    def _compute(self):
        self.state_data.speed_limit_kmh = self.speed_limit.get()
        target_rpm = self.state_data.target_motor_rpm
        mode = self.state_data.mode
        if target_rpm == 0:
            req = required_torque_85kg(self.grade.get())
            return {
                "mode": mode, "target_rpm": 0, "actual_rpm": 0.0, "current": 0.0, "ring": 0.0,
                "chainring": 0.0, "wheel": 0.0, "speed": 0.0, "ring_torque": 0.0,
                "motor_torque": 0.0, "available": 0.0, "required": req,
                "margin": -req, "decision": "Waiting for UP button"
            }
        current = CURRENT_MAP[mode][target_rpm]
        motor_tw = motor_torque_at_wheel(mode, target_rpm, CADENCE_RPM)
        ring_torque_val = motor_torque_at_ring(mode, target_rpm)
        available = motor_tw + RIDER_TORQUE_NM
        required = required_torque_85kg(self.grade.get())
        margin = available - required
        if required > 0 and available < required:
            ratio = clamp(available / required, 0.35, 1.0)
            actual_rpm = target_rpm * ratio
            decision = "Torque shortage · actual RPM drops · auto mode-up if ≥10%"
        elif required > 0 and available > required * 1.05:
            # Low-load / surplus condition.
            # Revised investor-demo behavior:
            #   - Actual RPM can still rise above the selected target.
            #   - However, in normal flat-road cruising it should not jump too quickly toward 2000 RPM.
            #   - The rise is softened, and normal automatic overspeed is limited to about +20%.
            surplus = clamp((available / required - 1.05) / 1.20, 0.0, 1.0)
            normal_overspeed_cap = min(MAX_MOTOR_RPM, target_rpm * 1.20)
            actual_rpm = target_rpm + (normal_overspeed_cap - target_rpm) * surplus
            actual_rpm = min(MAX_MOTOR_RPM, max(float(target_rpm), actual_rpm))
            if actual_rpm >= target_rpm * 1.10 and mode != "F":
                decision = "Torque surplus · actual RPM rises moderately · 3s downshift timer"
            elif actual_rpm >= target_rpm * 1.10 and mode == "F":
                decision = "Low-load surplus · F mode limits current and moderates RPM rise"
            else:
                decision = "Target RPM maintained with small surplus"
        else:
            actual_rpm = float(target_rpm)
            decision = "Target RPM maintained"
        return {
            "mode": mode, "target_rpm": target_rpm, "actual_rpm": actual_rpm, "current": current,
            "ring": ring_rpm(actual_rpm), "chainring": chainring_rpm(CADENCE_RPM, actual_rpm),
            "wheel": wheel_rpm(CADENCE_RPM, actual_rpm), "speed": speed_kmh(wheel_rpm(CADENCE_RPM, actual_rpm)),
            "ring_torque": ring_torque_val, "motor_torque": motor_tw, "available": available,
            "required": required, "margin": margin, "decision": decision,
        }

    def _auto_logic(self, result, dt=0.5):
        mode = self.state_data.mode
        target = result["target_rpm"]
        actual = result["actual_rpm"]
        if self.state_data.boost_ticks > 0:
            self.state_data.boost_ticks -= 1
            if self.state_data.boost_ticks == 0:
                self.state_data.mode = DEFAULT_MODE
                self.status.set("BOOST FINISHED · returned to default E mode")
                self._refresh_table()
            return
        if target <= 0 or mode == BOOST_MODE:
            return
        if actual <= target * 0.90:
            new_mode = step_mode_up(mode)
            self.state_data.surplus_seconds = 0.0
            if new_mode != mode:
                self.state_data.mode = new_mode
                self.status.set(f"AUTO MODE-UP · RPM drop ≥10% · {mode} → {new_mode} · more current supplied")
                self._refresh_table()
        elif actual >= target * 1.10:
            self.state_data.surplus_seconds += dt
            if self.state_data.surplus_seconds >= 3.0:
                new_mode = step_mode_down(mode)
                self.state_data.surplus_seconds = 0.0
                if new_mode != mode:
                    self.state_data.mode = new_mode
                    self.status.set(f"AUTO MODE-DOWN · surplus ≥10% for 3s · {mode} → {new_mode} · energy saving")
                    self._refresh_table()
        else:
            self.state_data.surplus_seconds = 0.0

    def _draw_visual(self, result):
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 420)
        h = max(c.winfo_height(), 300)
        margin = 34
        c.create_rectangle(16, 16, w-16, 72, fill="#0F172A", outline="#243244")
        c.create_text(32, 34, text="SS1 mechanical relation", fill="#93C5FD", anchor="w", font=("Segoe UI", 9, "bold"))
        c.create_text(32, 52, text="Wheel RPM = (20/28) × [ 3×Cadence + 2×MotorRPM/32 ]", fill="#F9FAFB", anchor="w", font=("Consolas", 11, "bold"))
        c.create_text(w-32, 52, text="Actual RPM cap: 2000", fill="#FBBF24", anchor="e", font=("Segoe UI", 10, "bold"))

        max_t = max(40.0, result["required"] * 1.15, result["available"] * 1.15)
        bar_left = margin
        bar_right = w - margin
        bar_w = bar_right - bar_left
        y0 = 115
        bars = [
            ("Required torque", result["required"], "#F97316"),
            ("Available torque", result["available"], "#22C55E" if result["margin"] >= 0 else "#EF4444"),
            ("Motor wheel torque", result["motor_torque"], "#38BDF8"),
            ("Rider torque", RIDER_TORQUE_NM, "#A78BFA"),
        ]
        for i, (label, val, color) in enumerate(bars):
            y = y0 + i*46
            c.create_text(bar_left, y-10, text=label, fill="#9CA3AF", anchor="w", font=("Segoe UI", 9, "bold"))
            c.create_rectangle(bar_left, y, bar_right, y+18, fill="#1F2937", outline="")
            fill_w = bar_w * clamp(val / max_t, 0, 1)
            c.create_rectangle(bar_left, y, bar_left + fill_w, y+18, fill=color, outline="")
            c.create_text(bar_left + fill_w + 8, y+9, text=f"{val:.1f} Nm", fill="#F9FAFB", anchor="w", font=("Consolas", 10, "bold"))

        y = h - 58
        c.create_text(bar_left, y-25, text="Motor RPM response", fill="#9CA3AF", anchor="w", font=("Segoe UI", 9, "bold"))
        c.create_line(bar_left, y, bar_right, y, fill="#334155", width=8, capstyle="round")
        target_x = bar_left + bar_w * clamp(result["target_rpm"] / MAX_MOTOR_RPM, 0, 1)
        actual_x = bar_left + bar_w * clamp(result["actual_rpm"] / MAX_MOTOR_RPM, 0, 1)
        c.create_line(bar_left, y, target_x, y, fill="#FBBF24", width=8, capstyle="round")
        c.create_oval(target_x-7, y-7, target_x+7, y+7, fill="#FBBF24", outline="white")
        c.create_oval(actual_x-8, y-8, actual_x+8, y+8, fill="#38BDF8", outline="white")
        c.create_text(target_x, y+24, text=f"Target {result['target_rpm']:.0f}", fill="#FBBF24", font=("Consolas", 9, "bold"))
        c.create_text(actual_x, y-24, text=f"Actual {result['actual_rpm']:.0f}", fill="#38BDF8", font=("Consolas", 9, "bold"))

    def _draw_hero(self, result):
        c = self.hero_canvas
        c.delete("all")
        w = max(c.winfo_width(), 460)
        h = max(c.winfo_height(), 150)

        # Background
        c.create_rectangle(0, 0, w, h, fill="#070B16", outline="")

        # Left current meter
        meter_x, meter_y, meter_h, meter_w = 18, 24, 84, 10
        c.create_rectangle(meter_x, meter_y, meter_x+meter_w, meter_y+meter_h, fill="#111827", outline="#334155")
        current = result["current"]
        fill_h = meter_h * clamp(current / 14.0, 0, 1)
        c.create_rectangle(meter_x, meter_y+meter_h-fill_h, meter_x+meter_w, meter_y+meter_h, fill="#4ADE80", outline="")
        c.create_text(meter_x + 5, meter_y - 10, text="Current", fill="#9CA3AF", font=("Segoe UI", 8, "bold"), anchor="s")
        c.create_text(meter_x + 5, meter_y + meter_h + 12, text=f"{current_text(current)}", fill="#86EFAC", font=("Consolas", 8, "bold"), anchor="n")

        # Decorative road / slope
        base_y = h - 24
        slope = self.grade.get()
        rise = 16 + slope * 1.5
        c.create_polygon(0, base_y, w*0.72, base_y-rise, w, base_y-rise+8, w, h, 0, h, fill="#3F3F55", outline="")
        c.create_line(0, base_y, w*0.72, base_y-rise, fill="#6B7280", width=2)

        # Wheel and drivetrain icon
        wheel_x = w * 0.40
        wheel_y = base_y - 22
        wheel_r = 15
        c.create_oval(wheel_x-wheel_r, wheel_y-wheel_r, wheel_x+wheel_r, wheel_y+wheel_r, outline="#E5E7EB", width=2)
        for ang in range(0, 360, 60):
            rad = math.radians(ang + (result['actual_rpm'] % 360) / 8)
            c.create_line(wheel_x, wheel_y, wheel_x + wheel_r*0.9*math.cos(rad), wheel_y + wheel_r*0.9*math.sin(rad), fill="#F59E0B", width=1)
        c.create_oval(wheel_x-3, wheel_y-3, wheel_x+3, wheel_y+3, fill="#F59E0B", outline="")

        crank_x = wheel_x + 42
        crank_y = wheel_y - 2
        c.create_oval(crank_x-10, crank_y-10, crank_x+10, crank_y+10, outline="#CBD5E1", width=2)
        arm_ang = math.radians((result['wheel'] * 2.5) % 360)
        c.create_line(crank_x, crank_y, crank_x + 16*math.cos(arm_ang), crank_y - 16*math.sin(arm_ang), fill="#93C5FD", width=3)
        c.create_oval(crank_x+14*math.cos(arm_ang)-3, crank_y-14*math.sin(arm_ang)-3,
                      crank_x+14*math.cos(arm_ang)+3, crank_y-14*math.sin(arm_ang)+3, fill="#93C5FD", outline="")

        motor_x = crank_x + 38
        motor_y = crank_y + 6
        c.create_oval(motor_x-8, motor_y-8, motor_x+8, motor_y+8, outline="#60A5FA", width=2)
        c.create_line(crank_x+10, crank_y+4, motor_x-8, motor_y, fill="#60A5FA", width=2, dash=(4, 2))
        c.create_text(motor_x, motor_y+22, text="Motor", fill="#93C5FD", font=("Segoe UI", 8, "bold"))

        # Flow arrow
        c.create_line(wheel_x+18, wheel_y, crank_x-14, crank_y, fill="#38BDF8", width=2, arrow=tk.LAST)
        c.create_line(crank_x+12, crank_y+3, motor_x-12, motor_y+1, fill="#22C55E", width=2, arrow=tk.LAST)

        # Right-side badges
        badge_y = 24
        c.create_round_rect = None
        badge1 = (w - 150, badge_y, w - 18, badge_y + 26)
        c.create_rectangle(*badge1, fill="#0F172A", outline="#334155")
        c.create_text(badge1[0]+10, badge_y+13, text=f"Actual {result['actual_rpm']:.0f} rpm", fill="#F8FAFC", anchor="w", font=("Consolas", 9, "bold"))
        badge2 = (w - 128, badge_y + 34, w - 18, badge_y + 60)
        c.create_rectangle(*badge2, fill="#0F172A", outline="#334155")
        c.create_text(badge2[0]+10, badge2[1]+13, text=f"{result['speed']:.1f} km/h", fill="#38BDF8", anchor="w", font=("Consolas", 9, "bold"))
        badge3 = (w - 160, badge_y + 68, w - 18, badge_y + 94)
        c.create_rectangle(*badge3, fill="#0F172A", outline="#334155")
        c.create_text(badge3[0]+10, badge3[1]+13, text=f"Torque margin {result['margin']:+.1f} Nm", fill=("#86EFAC" if result['margin'] >= 0 else "#FCA5A5"), anchor="w", font=("Consolas", 9, "bold"))

        # Title hints
        c.create_text(18, 14, text="Live scene", fill="#BFDBFE", anchor="w", font=("Segoe UI", 8, "bold"))
        c.create_text(18, h-8, text=f"Grade {self.grade.get():.1f}% · Target {result['target_rpm']:.0f} rpm · Max actual 2000 rpm", fill="#9CA3AF", anchor="w", font=("Segoe UI", 8))

        # Update mode badge
        self.hero_mode_badge.config(text=f"Mode {result['mode']}")
        if result['mode'] == 'X':
            self.hero_mode_badge.config(bg="#5B1320", fg="#FECACA")
        elif result['margin'] >= 0:
            self.hero_mode_badge.config(bg="#12335F", fg="#BFDBFE")
        else:
            self.hero_mode_badge.config(bg="#4C1D1D", fg="#FECACA")

    def _update_loop(self):
        result = self._compute()
        good = result["margin"] >= 0
        self.kpis["speed"].set_value(f"{result['speed']:.1f}", "km/h")
        self.kpis["mode"].set_value(result["mode"], f"{current_text(result['current'])} mapped")
        self.kpis["margin"].set_value(f"{result['margin']:+.1f}", "Nm", good=good)
        self.kpis["rpm"].set_value(f"{result['target_rpm']:.0f} / {result['actual_rpm']:.0f}", "target / actual · max 2000")

        self.grade_label.config(text=f"{self.grade.get():.1f}%")
        self.limit_label.config(text=f"{self.speed_limit.get():.1f} km/h")
        self.values["mode"].set(result["mode"])
        self.values["target_rpm"].set(f"{result['target_rpm']:.0f} rpm")
        self.values["actual_rpm"].set(f"{result['actual_rpm']:.0f} rpm")
        self.values["current"].set(current_text(result["current"]))
        self.values["cadence"].set(f"{CADENCE_RPM:.0f} rpm")
        self.values["ring"].set(f"{result['ring']:.1f} rpm")
        self.values["chainring"].set(f"{result['chainring']:.1f} rpm")
        self.values["wheel"].set(f"{result['wheel']:.1f} rpm")
        self.values["speed"].set(f"{result['speed']:.1f} km/h")
        self.values["ring_torque"].set(f"{result['ring_torque']:.1f} Nm")
        self.values["motor_torque"].set(f"{result['motor_torque']:.1f} Nm")
        self.values["rider_torque"].set(f"{RIDER_TORQUE_NM:.1f} Nm")
        self.values["available_torque"].set(f"{result['available']:.1f} Nm")
        self.values["required_torque"].set(f"{result['required']:.2f} Nm")
        self.values["margin"].set(f"{result['margin']:+.2f} Nm")
        self.values["decision"].set(result["decision"])
        self._draw_visual(result)
        self._draw_hero(result)
        self._auto_logic(result)
        self.after(500, self._update_loop)

    def reset(self):
        self.state_data = SimState(speed_limit_kmh=self.speed_limit.get())
        self.status.set("RESET · motor RPM 0 · default mode E")
        self._refresh_table()

    def motor_up(self):
        self.state_data.motor_index = min(len(MOTOR_STEPS) - 1, self.state_data.motor_index + 1)
        self.status.set("UP · target motor RPM step increased")
        self._refresh_table()

    def motor_down(self):
        self.state_data.motor_index = max(0, self.state_data.motor_index - 1)
        self.status.set("DOWN · target motor RPM step decreased")
        self._refresh_table()

    def boost(self):
        if self.state_data.target_motor_rpm == 0:
            self.state_data.motor_index = 1
        self.state_data.mode = BOOST_MODE
        self.state_data.boost_ticks = 20
        self.status.set("X BOOST · 14A output for about 10 seconds")
        self._refresh_table()

    def manual_mode_up(self):
        self.state_data.mode = step_mode_up(self.state_data.mode)
        self.status.set("MANUAL · current stage increased")
        self._refresh_table()

    def manual_mode_down(self):
        self.state_data.mode = step_mode_down(self.state_data.mode)
        self.status.set("MANUAL · current stage decreased")
        self._refresh_table()

    def toggle_speed_limit(self):
        self.state_data.speed_limit_enabled = not self.state_data.speed_limit_enabled
        self.status.set(f"SPEED LIMIT · {'enabled' if self.state_data.speed_limit_enabled else 'disabled'}")
        self._refresh_table()


if __name__ == "__main__":
    InvestorDemo().mainloop()
