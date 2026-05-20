# Assets

Drop production icons here before packaging:

- `icon.icns` — macOS app icon (1024×1024 source)
- `icon.ico` — Windows app icon (256×256 multi-res)
- `icon.png` — 512×512 source PNG (used by Linux AppImage)

Suggested tooling:
- macOS: `iconutil` from a `.iconset` directory
- Windows: ImageMagick (`magick convert icon.png -define icon:auto-resize=256,128,64,48,32,16 icon.ico`)
- All from one source: [electron-icon-builder](https://www.npmjs.com/package/electron-icon-builder)

Until real icons are added, electron-builder will fall back to its default placeholder.
