"""Calculs purs de la session (aucun Qt) : géométrie de l'écran virtuel.

Extrait de `PhonePanel.start()` : cette logique ne dépendait que de nombres, mais lisait des widgets au milieu du calcul.
Séparée de l'interface, elle se teste sans fenêtre et pourra servir ailleurs (ligne de commande, autre interface).
"""

from __future__ import annotations

from dataclasses import dataclass

FIXED_SHAPES = {"16:9": 16 / 9, "2:1": 2.0, "21:9": 21 / 9}


@dataclass(frozen=True)
class DisplayRequest:
    """Tout ce que le calcul doit savoir, lu une fois dans l'interface puis transmis tel quel."""

    mode: str  # « horizontal » (écran virtuel) ou autre (écran du téléphone)
    width: int
    height: int
    dpi: int
    shape: str  # « auto », « 16:9 », « 2:1 », « 21:9 »
    area_w: int  # taille de la zone d'affichage en pixels logiques
    area_h: int
    native: bool  # « image nette » : 1 pixel vidéo = 1 pixel écran
    pixel_ratio: float  # devicePixelRatio de la fenêtre
    zoom_percent: int  # curseur « taille de l'interface du jeu »


@dataclass(frozen=True)
class DisplayPlan:
    new_display: str  # argument scrcpy « LxH/dpi » ; vide = écran du téléphone
    max_size: int  # plafond de taille en mode écran du téléphone ; 0 en mode écran virtuel
    ratio: float | None  # largeur/hauteur de l'écran virtuel ; None hors mode virtuel


def plan_display(req: DisplayRequest) -> DisplayPlan:
    if req.mode != "horizontal":
        return DisplayPlan("", max(req.width, req.height), None)
    w, h = max(req.width, req.height, 1), max(min(req.width, req.height), 1)  # jamais de division par zéro
    has_area = req.area_w > 300 and req.area_h > 200
    if req.shape == "auto" and has_area:
        # même forme que la zone d'affichage (entre 4:3 et 21:9) : plus de bandes noires
        ratio = min(max(req.area_w / req.area_h, 1.33), 2.4)
        h = max(480, int(w / ratio) // 8 * 8)
    elif req.shape in FIXED_SHAPES:
        h = max(480, int(w / FIXED_SHAPES[req.shape]) // 8 * 8)
    base_dpi = float(req.dpi)
    if req.native and has_area:
        # 1 pixel de vidéo = 1 pixel d'écran : on dimensionne l'écran virtuel sur la zone affichée
        r = w / h
        fit_w = min(req.area_w, req.area_h * r) * req.pixel_ratio
        nw = max(960, min(w, int(fit_w) // 8 * 8))
        if nw < w:
            base_dpi = req.dpi * nw / w
            w, h = nw, max(480, int(nw / r) // 8 * 8)
    dpi = max(120, min(640, int(base_dpi * req.zoom_percent / 100)))
    return DisplayPlan(f"{w}x{h}/{dpi}", 0, w / h)
