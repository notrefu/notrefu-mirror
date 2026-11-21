"""Santé du téléphone (batterie, chauffe, processeur, mémoire, stockage), débit estimé et temps de jeu.

Tout est lu par adb (`dumpsys battery`, `df`, `/proc/meminfo`, `/proc/stat`) : aucune installation sur le téléphone.
Les fonctions d'analyse ne dépendent pas de Qt et sont testées à part.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEP_T, SEP_S, SEP_M, SEP_C = "@@T", "@@S", "@@M", "@@C"
CPU_SAMPLE_S = 0.4  # écart entre les deux lectures de /proc/stat (le % de processeur est une différence entre deux instants)

# Une seule commande adb pour tout lire (une connexion de moins par relevé).
READ_COMMAND = (
    f"dumpsys battery; echo {SEP_T}; dumpsys thermalservice 2>/dev/null | grep -m1 'Thermal Status'; "
    f"echo {SEP_S}; df -k /data 2>/dev/null | tail -n 1; echo {SEP_M}; grep -E 'MemTotal|MemAvailable' /proc/meminfo; "
    f"echo {SEP_C}; if head -n 1 /proc/stat >/dev/null 2>&1; then head -n 1 /proc/stat; sleep {CPU_SAMPLE_S}; head -n 1 /proc/stat; "
    "else dumpsys cpuinfo 2>/dev/null | grep -m1 TOTAL; fi"
)

# Relevé léger (toutes les ~5 s) : seulement des lectures /proc, pas de dumpsys (qui coûte cher au téléphone).
LIGHT_COMMAND = (
    f"grep -E 'MemTotal|MemAvailable' /proc/meminfo; echo {SEP_C}; "
    f"if head -n 1 /proc/stat >/dev/null 2>&1; then head -n 1 /proc/stat; sleep {CPU_SAMPLE_S}; head -n 1 /proc/stat; fi"
)

RAM_EXPLAIN = (
    "Mémoire globale de l'appareil Android (système, services, cache et jeu), pas uniquement celle du jeu. "
    "Utilisée = mémoire totale − mémoire disponible."
)

GLOBAL_NOTE = (
    "CPU et RAM : valeurs globales de l'appareil Android (tous les processus), pas celles du jeu seul. "
    "RAM = mémoire totale − mémoire disponible ; « jeu » = mémoire de l'application seule."
)


@dataclass
class Health:
    level: int | None = None  # % de batterie
    temp_c: float | None = None  # température de la batterie
    charging: bool = False
    thermal: int | None = None  # 0 normal … 6 arrêt d'urgence (échelle Android)
    free_gb: float | None = None  # stockage libre
    mem_mb: int | None = None  # mémoire disponible
    mem_total_mb: int | None = None
    cpu_pct: int | None = None  # charge du processeur du téléphone, 0–100
    game_mb: int | None = None  # mémoire (PSS) utilisée par l'application du jeu, d'après `dumpsys meminfo <paquet>`
    stamp: float = 0.0
    extra: dict = field(default_factory=dict)

    def summary(self) -> str:
        """Texte court de la barre : « 82 % · 36,5 °C · CPU 23 % · RAM 64 % » (le stockage n'y est plus : voir les alertes)."""
        parts = []
        if self.level is not None:
            parts.append(f"{self.level} %" + (" ⚡" if self.charging else ""))
        if self.temp_c is not None:
            parts.append(f"{self.temp_c:.1f} °C".replace(".", ","))
        if self.cpu_pct is not None:
            parts.append(f"CPU {self.cpu_pct} %")
        if self.ram_pct is not None:  # RAM de TOUT le téléphone (total − disponible) ; « jeu » = l'application seule
            parts.append(f"RAM {self.ram_pct} %" + (f" (jeu {self.game_mb} Mo)" if self.game_mb else ""))
        return " · ".join(parts)

    @property
    def ram_pct(self) -> int | None:
        """Mémoire utilisée, en % (mémoire totale moins mémoire disponible)."""
        if self.mem_mb is None or not self.mem_total_mb or self.mem_total_mb <= 0:
            return None
        return max(0, min(100, round(100 * (1 - self.mem_mb / self.mem_total_mb))))


def parse_battery(text: str) -> tuple[int | None, float | None, bool]:
    level = temp = None
    charging = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("level:"):
            level = _int(line)
        elif line.startswith("temperature:"):
            t = _int(line)
            temp = t / 10 if t is not None else None  # dixièmes de degré
        elif line.startswith("status:"):
            charging = charging or _int(line) == 2  # 2 = en charge
        elif line in ("AC powered: true", "USB powered: true", "Wireless powered: true"):
            charging = True
    return level, temp, charging


def _int(line: str) -> int | None:
    m = re.search(r"-?\d+", line.split(":", 1)[1] if ":" in line else line)
    return int(m.group(0)) if m else None


def parse_thermal(text: str) -> int | None:
    m = re.search(r"Thermal Status:\s*(\d+)", text)
    return int(m.group(1)) if m else None


def parse_df(text: str) -> float | None:
    """Dernière ligne de `df -k /data` : Filesystem 1K-blocks Used Available Use% Mounted."""
    cols = text.split()
    if len(cols) >= 4 and cols[3].isdigit():
        return int(cols[3]) / (1024 * 1024)
    return None


def parse_mem(text: str) -> int | None:
    m = re.search(r"MemAvailable:\s*(\d+)\s*kB", text)
    return int(m.group(1)) // 1024 if m else None


def parse_mem_total(text: str) -> int | None:
    m = re.search(r"MemTotal:\s*(\d+)\s*kB", text)
    return int(m.group(1)) // 1024 if m else None


def parse_pkg_meminfo(text: str) -> int | None:
    """Mémoire de l'application en Mo d'après `dumpsys meminfo <paquet>` : « TOTAL PSS: 512345 » (Android 10+) ou la ligne
    « TOTAL 512345 … » du tableau (versions plus anciennes). Les valeurs sont en Ko."""
    m = re.search(r"TOTAL PSS:\s*(\d+)", text) or re.search(r"^\s*TOTAL\s+(\d+)", text, re.M)
    return int(m.group(1)) // 1024 if m else None


def parse_cpu(text: str) -> int | None:
    """Charge du processeur en %. Deux lectures de /proc/stat (« cpu  user nice system idle iowait irq softirq steal… »)
    donnent la part de temps occupé entre elles ; à défaut, la ligne TOTAL de `dumpsys cpuinfo`."""
    samples = []
    for line in text.splitlines():
        cols = line.split()
        if cols and cols[0] == "cpu" and len(cols) >= 5 and all(c.isdigit() for c in cols[1:5]):
            vals = [int(c) for c in cols[1:9] if c.isdigit()]
            samples.append((sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0)))  # (total, inactif)
    if len(samples) >= 2:
        d_total, d_idle = samples[1][0] - samples[0][0], samples[1][1] - samples[0][1]
        if d_total > 0:
            return max(0, min(100, round(100 * (1 - d_idle / d_total))))
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)%\s*TOTAL", text)
    return max(0, min(100, round(float(m.group(1).replace(",", "."))))) if m else None


def parse(output: str) -> Health:
    """Analyse la sortie de READ_COMMAND."""
    b, rest = output.split(SEP_T, 1) if SEP_T in output else (output, "")
    t, rest = rest.split(SEP_S, 1) if SEP_S in rest else (rest, "")
    s, rest = rest.split(SEP_M, 1) if SEP_M in rest else (rest, "")
    m, c = rest.split(SEP_C, 1) if SEP_C in rest else (rest, "")
    level, temp, charging = parse_battery(b)
    return Health(level, temp, charging, parse_thermal(t), parse_df(s), parse_mem(m), mem_total_mb=parse_mem_total(m),
                  cpu_pct=parse_cpu(c))


def format_mem(mb: float) -> str:
    """Taille lisible : « 512 Mo » sous 1 Go, sinon « 5,2 Go » (virgule française)."""
    if mb >= 1024:
        return f"{mb / 1024:.1f}".replace(".", ",") + " Go"
    return f"{round(mb)} Mo"


def ram_detail(h: "Health | None") -> str:
    """Détail de la RAM pour l'info-bulle : globale utilisée / totale, jeu seul, explication. Gère les valeurs absentes."""
    if h is None:
        return "RAM : en attente du premier relevé…\n" + RAM_EXPLAIN
    lines = []
    if h.mem_total_mb and h.mem_mb is not None and h.ram_pct is not None:
        used = max(0, h.mem_total_mb - h.mem_mb)
        total_txt = format_mem(h.mem_total_mb)
        used_txt = format_mem(used)
        if used_txt.endswith(total_txt[-2:]):  # même unité : « 5,2 / 8,0 Go »
            used_txt = used_txt.rsplit(" ", 1)[0]
        lines.append(f"RAM de l'appareil : {used_txt} / {total_txt} utilisés ({h.ram_pct} %)")
    else:
        lines.append("RAM de l'appareil : indisponible (relevé en attente ou /proc/meminfo illisible)")
    lines.append(f"Jeu : ~{format_mem(h.game_mb)}" if h.game_mb else "Jeu : non disponible (en attente ou dumpsys meminfo indisponible)")
    lines.append(RAM_EXPLAIN)
    return "\n".join(lines)


def parse_light(output: str) -> Health:
    """Analyse la sortie de LIGHT_COMMAND (mémoire + processeur)."""
    m, c = output.split(SEP_C, 1) if SEP_C in output else (output, "")
    return Health(mem_mb=parse_mem(m), mem_total_mb=parse_mem_total(m), cpu_pct=parse_cpu(c))


def merge_full(prev: "Health | None", full: Health) -> Health:
    """Relevé complet sans RAM du jeu (relevé espacé) : on garde la dernière valeur connue."""
    if prev is not None and full.game_mb is None:
        full.game_mb = prev.game_mb
    return full


def merge_light(prev: "Health | None", light: Health) -> Health:
    """Relevé léger + dernières valeurs lentes (batterie, chauffe, stockage, RAM du jeu) du relevé complet précédent."""
    if prev is None:
        return light
    for f in ("level", "temp_c", "charging", "thermal", "free_gb", "game_mb"):
        setattr(light, f, getattr(prev, f))
    return _fill_mem(prev, light)


def _fill_mem(prev: "Health", light: Health) -> Health:
    if light.mem_mb is None:
        light.mem_mb, light.mem_total_mb = prev.mem_mb, prev.mem_total_mb
    if light.cpu_pct is None:
        light.cpu_pct = prev.cpu_pct
    return light


# --- alertes -------------------------------------------------------------------------------------------------------
BATTERY_LOW, BATTERY_CRIT = 20, 10
TEMP_WARM, TEMP_HOT = 42.0, 45.0
STORAGE_LOW_GB = 3.0
MEMORY_LOW_MB = 600


def alerts(h: Health) -> list[tuple[str, str, bool]]:
    """Alertes en cours : (clé, texte, grave)."""
    out: list[tuple[str, str, bool]] = []
    if h.level is not None and not h.charging:
        if h.level <= BATTERY_CRIT:
            out.append(("battery", f"Batterie critique ({h.level} %) : branche le chargeur.", True))
        elif h.level <= BATTERY_LOW:
            out.append(("battery", f"Batterie faible ({h.level} %).", False))
    if h.temp_c is not None:
        if h.temp_c >= TEMP_HOT:
            out.append(("heat", f"Le téléphone chauffe beaucoup ({h.temp_c:.0f} °C) : baisse la qualité ou fais une pause.", True))
        elif h.temp_c >= TEMP_WARM:
            out.append(("heat", f"Le téléphone chauffe ({h.temp_c:.0f} °C).", False))
    if h.thermal is not None and h.thermal >= 3:
        out.append(("thermal", "Le téléphone bride ses performances à cause de la chauffe : le jeu risque de ralentir.", True))
    if h.free_gb is not None and h.free_gb < STORAGE_LOW_GB:
        out.append(("storage", f"Stockage presque plein ({h.free_gb:.1f} Go libres).", False))
    if h.mem_mb is not None and h.mem_mb < MEMORY_LOW_MB:
        out.append(("memory", f"Mémoire du téléphone presque saturée ({h.mem_mb} Mo disponibles) : trop de comptes ?", False))
    return out


# --- débit estimé ------------------------------------------------------------------------------------------------------
WIFI_COMFORT_MBIT = 40  # au-delà, le Wi-Fi domestique commence à saccader
USB_LIMIT_MBIT = 300


def bandwidth_text(own: float, total: float, sessions: int, wireless: bool) -> str:
    """Phrase affichée sous la qualité : débit de cette fenêtre, total pour le téléphone, conseil."""
    base = f"Jusqu'à {own:g} Mbit/s pour cette fenêtre"
    if sessions > 1:
        base += f" · {total:g} Mbit/s au total pour {sessions} sessions sur ce téléphone"
    if wireless and total > WIFI_COMFORT_MBIT:
        return base + f". En Wi-Fi, au-delà de {WIFI_COMFORT_MBIT} Mbit/s ça saccade souvent : baisse le débit ou branche le câble."
    if not wireless and total > USB_LIMIT_MBIT:
        return base + ". C'est beaucoup, même pour de l'USB : baisse le débit."
    return base + "."


# --- durées -------------------------------------------------------------------------------------------------------------------
def format_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h} h {m:02d}" if h else f"{m} min"
