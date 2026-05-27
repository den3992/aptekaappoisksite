# AptekaA — brand logos

Source files for the AptekaA app icon.

## Files

| File | Purpose |
| --- | --- |
| `source.svg` | Vector wrapper referencing `source.png`. Use this in any context that wants an SVG. |
| `source.png` | 1024×1024 raster master generated via AI image-to-image (see note below). Single source of truth for all production rasters. |

## How the production icons were built

The production rasters in `../` (`favicon.ico`, `favicon-*.png`, `apple-touch-icon.png`, `icon-*.png`) are all downscaled from `source.png` via Lanczos resampling with a squircle alpha-mask applied for the rounded corners. The full build pipeline is reproducible:

```bash
python3 /app/icon_exports/build_from_ai.py
```

## Editing notes

- `source.png` is the canonical artwork. Any change to the icon should start by editing this file (or replacing it with a new master) and then re-running the build pipeline above.
- `source.svg` is NOT a parametric vector source — it embeds the raster. If a true editable vector source is ever needed, the earlier flat parametric design is preserved at `/app/icon_exports/svg/variant-a-large-capsule.svg` and can be re-vectorised from there.
