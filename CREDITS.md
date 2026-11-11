# Credits

- **Manual Shield** by REXCRAFT88: https://github.com/REXCRAFT88/OOT-Mods-by-rexcraft88, GPL-3.0. The manual
  shield, its controls (the shield on ZL, Z-targeting on L, R3 to cancel) and the crouch behind the shield
  in `src/shield.c` and `src/pad.c` are ported from its tag `manual-shield-v0.1.1` (commit 2c571f8).
  `ootmods/nup.py` reads a `.nup` game dump the way that project's `nup_reader.py` does.
- **Dungeon Blood** by REXCRAFT88. It is **not** part of this repository and is not offered for download here:
  its author withdrew it. The window only turns it on and off in a copy of the game that already has it.
- **Quick swap** grew out of [OoT Quick Item for Lichii](https://github.com/RickyZPR/OoT-Lichii-Quick-Item) by
  RickyZPR, itself built on Manual Shield.
- The module, the other mods (sprint, auto-jump, Hero Mode, the N64 hookshot targets), the installer and the
  window: RickyZPR, developed with Claude Code (Anthropic).
- Optional Python packages the installer can use: zstandard, lz4 and zbic. Their licenses come with the
  packages. When a Hookshot Builder is on the PC, the installer uses the Python and the ZBIC reader that
  the builder brings; neither is part of this repository.

This repository contains no Nintendo code or data, and no built game. The installer changes the user's own
copy of the game, and makes the hookshot targets from the user's own game files.
*The Legend of Zelda: Ocarina of Time* is © Nintendo. This project is not affiliated with Nintendo, with any
emulator, or with Hookshot.
