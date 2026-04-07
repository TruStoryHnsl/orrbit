# Orrbit — Brand

**Tagline:** Web File Server

![Orrbit logo](logo.png)

The image at `branding/logo.png` is the **definitive logo** for orrbit. It was
cropped from the authoritative icon sheet at
`~/projects/personal_icon_pack.png`. Do not substitute, recolor, or redraw.

> **Note:** The workspace `CLAUDE.md` also uses "orrbit" as the hostname of
> the Proxmox tower. This branding applies to the **Web File Server project**
> at `~/projects/orrbit/`, not to the hypervisor host. If the host ever needs
> its own mark, it should not reuse this atom.

## Glyph

A Bohr-model atom rendered in copper — a dense nucleus at center, three
electron orbits crossing at oblique angles, small copper beads marking the
electrons. The implication: files as particles, orbiting a single served
nucleus, reachable from any angle.

## Color palette

| Role       | Hex        | Name            | Use                                     |
|------------|------------|-----------------|-----------------------------------------|
| Primary    | `#784808`  | Copper Ring     | Brand copper, orbit strokes, links      |
| Highlight  | `#884808`  | Polished Copper | Hover, active file row                  |
| Mid        | `#683808`  | Dark Copper     | Secondary text, breadcrumb dividers     |
| Deep       | `#582808`  | Umber Orbit     | Borders, outlines on light surfaces     |
| Shadow     | `#481808`  | Iron Core       | Dark-mode background, deep shadow       |
| Surface    | `#F5EAD0`  | Cream Disk      | Light-mode card bodies, the halo tone   |

## Usage

- Cream Disk is **borrowed from the glyph's own backdrop** — it's the only
  warm off-white permitted on orrbit surfaces. Never substitute plain white.
- The copper orbits in the UI should always cross at the same three
  angles as the glyph (roughly 0°, 60°, 120°) if reused as a loading spinner
  or decorative motif.
- Do **not** recolor orrbit copper to red or orange — the warmth is the
  whole identity. Red reads "error"; copper reads "archive".
- Minimum clear space = 20% of bounding box (the orbits visually overflow
  the nucleus, so they need more breathing room than typical marks).
