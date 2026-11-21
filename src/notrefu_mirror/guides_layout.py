"""Calcul de largeur du panneau Guides (sans Qt) : il prend la place laissée libre à côté du jeu."""

from __future__ import annotations

MIN_PANEL = 260
TOLERANCE = 6


def autofit_width(*, total: int, handle: int, host_w: int, host_h: int, page_w: int, aspect: float, current: int) -> int | None:
    """Largeur à donner au panneau pour que le jeu garde toute sa hauteur sans bandes noires ; None = ne rien changer."""
    extra = page_w - host_w  # marges éventuelles autour de l'écran du jeu
    game_w = int(host_h * aspect) + max(0, extra) + handle
    target = max(MIN_PANEL, min(total - game_w, total - MIN_PANEL))
    return target if abs(target - current) > TOLERANCE else None
