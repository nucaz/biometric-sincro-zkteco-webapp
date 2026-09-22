"""
Inline-SVG icon set for the sidebar nav (central/templates/base.html).

Deliberately built from primitives (circle/rect/line/polyline/polygon/
ellipse) wherever a recognizable icon can be made from them, instead of
hand-typed <path> bezier data -- a typo in a 'd' attribute fails silently
(a blank icon, no error anywhere) and there's no automated way to visually
spot-check dozens of hand-drawn curves. The few paths used are short,
extremely common ones (log-out, lock shackle) chosen for that reason.

Each value is the INNER markup of a 24x24 viewBox stroke icon -- the
caller (see `icon()` in webapp.py) wraps it in the <svg> tag itself.
"""

ICONS = {
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "alert-circle": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
    "trending-up": '<polyline points="1 17 8 10 13 15 23 5"/><polyline points="17 5 23 5 23 11"/>',
    "server": '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
    "users": '<circle cx="9" cy="7" r="3"/><rect x="3" y="13" width="12" height="7" rx="2"/><circle cx="17" cy="8" r="2.3"/><rect x="14" y="14" width="8" height="6" rx="2"/>',
    "user-plus": '<circle cx="9" cy="7" r="4"/><rect x="2" y="14" width="14" height="7" rx="2"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="16" y1="11" x2="22" y2="11"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "calendar-minus": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="16" x2="15" y2="16"/>',
    "key": '<circle cx="8" cy="14" r="4"/><line x1="11" y1="11" x2="20" y2="2"/><line x1="16" y1="6" x2="19" y2="9"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><line x1="3" y1="5" x2="3" y2="19"/><line x1="21" y1="5" x2="21" y2="19"/><ellipse cx="12" cy="19" rx="9" ry="3"/>',
    "file-text": '<rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="16" y2="11"/><line x1="8" y1="15" x2="13" y2="15"/>',
    "shield": '<polygon points="12 2 20 6 20 12 12 22 4 12 4 6"/><polyline points="9 12 11 14 15 10"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><circle cx="12" cy="16" r="1.4"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    "chevrons-left": '<polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/>',
    "menu": '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
}
