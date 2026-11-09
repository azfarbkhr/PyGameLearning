# Character sprite sheets

Ten coordinated transparent character sheets cover the main cast and both armies. The sheets use **6 columns × 5 rows** ordered as idle, walk, attack, hit, and death. Character drawings have transparent padding; trim each cell's visible alpha bounds when deriving game-size frames. The exact sheet dimensions can vary slightly by generated asset.

| Row | Animation | Frames |
| --- | --- | --- |
| 1 | Idle / breathing | 6 |
| 2 | Walk cycle | 6 |
| 3 | Attack | 6 |
| 4 | Hit reaction | 6 |
| 5 | Death / fall | 6 |

All poses face screen-right. Flip frames horizontally for screen-left. Each action row is a frame sequence. The game crops transparent bounds and scales frames smoothly to fit the scene.

## Files

- `jon_snow_sheet.png`
- `ramsay_bolton_sheet.png`
- `sansa_stark_sheet.png`
- `sansa_archer_sheet.png` — Sansa's bow-ready animation, with a six-frame draw-and-release attack row.
- `tormund_giantsbane_sheet.png`
- `wun_wun_sheet.png`
- `arrow_projectile.png` — transparent steel-tipped projectile sprite. The game rotates it to its flight vector and adds a restrained motion trail.
- `bolton_soldier_sheet.png`
- `bolton_archer_sheet.png` — dedicated Bolton ranged unit with a bow draw-and-release attack row.
- `stark_soldier_sheet.png`
- `stark_archer_sheet.png` — male northern reinforcements with a dedicated bow draw-and-release attack row.

The sheets share a visual style and grid, while Wun Wun is intentionally larger in silhouette than the human characters. Bolton soldiers and Stark supporters fill out the battlefield ranks.
