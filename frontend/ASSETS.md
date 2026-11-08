# Clans asset pack and art direction

The owner's attached mobile reference is the visual target: a deep charcoal treasury, orange horizon, strong serif figures, quiet outlined cards and a floating five-position navigation. The requested light counterpart uses ivory and green. The reference is supplied in the conversation; its original attachment is not stored in this checkout.

Both backgrounds were generated with the **built-in image generation tool**, then copied into this project. No API-key/CLI fallback was used. They contain artwork only; typography, amounts and controls are real app elements. Original generated files were retained at their tool-provided location.

| Asset | Purpose |
| --- | --- |
| `public/assets/clans-night.png` | 1024×1536 charcoal, fine grain, restrained amber horizon and subtle topographic texture. |
| `public/assets/clans-day.png` | 1024×1536 ivory paper, sage illumination and forest-green horizon. |
| `public/assets/afribit-mark.png` | Existing AfriBit logo, copied from the sibling Insats application's shared brand assets; artwork unchanged. |
| `public/assets/icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | Existing logo mechanically rasterized on charcoal at192/512/180px through the browser, with safe padding. No new logo was invented. |
| `public/assets/fonts/manrope-latin-variable.woff2` | Manrope variable font, weights200–800. |
| `public/assets/fonts/cormorant-garamond-600.woff2`, `-700.woff2`, `-600-italic.woff2` | Editorial headings, numbers and italic brand accent. |
| `public/licenses/` | Font license notices copied from their source packages. |

Fonts come from the pinned Fontsource packages in `package-lock.json`. The font files and licenses are included so the design does not depend on a third-party font request. No paid font license is required for this pairing. UI icons use `@phosphor-icons/react` under MIT.

## Final generation prompts

### Midnight background

Use case: stylized-concept. Asset type: production background texture for an elegant mobile AfriBit Clans treasury app, portrait aspect ratio2:3. Create ONLY a background, no mockup, no phone, no UI, no text, no icons. Almost black charcoal black background, luxurious extremely subtle fine film grain, subtle shadowy African topographic contours barely visible at bottom. A single very fine glowing amber-orange elliptical horizon arc enters at the lower left at about60% height and rises gracefully towards the right edge at25% height. Restrained diffuse warm copper light emanates from behind the upper-right part of the arc. The center and left upper area must remain clean deep black for large white balance text. The lower two thirds mostly near-black, very low contrast, usable behind readable cards. Refined cinematic premium financial app aesthetic. Keep it minimal, not science fiction, not neon, no gold glitter, no large objects, no excessive waves. Palette near-black #0c0d0c, charcoal #151614, burnished orange #f68b11. High resolution crisp fine line.

### Daylight background

Use case: stylized-concept. Asset type: production background texture for an elegant mobile AfriBit Clans treasury app light theme, portrait aspect ratio2:3. Create ONLY a background, no mockup, no phone, no UI, no text, no icons. Warm ivory white paper background #f6f5ee with extremely subtle natural fine paper grain. A single very fine forest-green elliptical horizon arc enters at lower left about60% height and rises gracefully towards right edge at25% height. Soft restrained sage-green ambient illumination on the right behind the arc, like diffused light through green silk. Center and left upper area must remain clean very pale ivory for dark typography. Lower two thirds almost flat pale ivory, a few barely visible quiet African topographic contours bottom. Refined premium financial app, quiet luxury printed banknote material, restrained and spacious. Palette warm white #f6f5ee, pale sage #e3eadf, forest green #20734d. Absolutely no orange, no large objects, no leaf illustrations, no text, no gradients that look digitally banded.

## Design tokens

Midnight: background `#0c0d0c`, surface `#181917`, primary text `#f5f4ed`, accent `#ff940b`. Daylight: background `#f6f5ee`, surface `#fdfcf7`, primary text `#202b22`, accent `#256f49`. Complete tokens and responsive rules: `src/styles.css`. Layout uses normal app content, not a decorative phone frame or imitation device status bar.

The portable pack is `output/afribit-clans-assets.zip` at the repository root. Screenshots in `output/playwright/` show both themes and the grant review screen.


## November 3 navigation update

Sora now supplies strong screen headings; Space Grotesk supplies money figures with tabular digits. Manrope remains the body font, and the wordmark retains Cormorant Garamond. Both additions come from pinned Fontsource variable packages at version 5.3.0, with OFL notices in `public/licenses/`. Primary projects: [Sora](https://github.com/sora-xor/sora-font) and [Space Grotesk](https://github.com/floriankarsten/space-grotesk).

The current app serves `clans-night.webp`, `clans-day.webp`, `home-paw-dark.webp`, `home-paw-light.webp` and `afribit-mark.webp`. `scripts/optimize-assets.mjs` mechanically exports these through Sharp, preserving the source PNGs. The four background/button exports total 85,952 bytes; their originals total 6,512,445 bytes. Artwork remains decorative, with real text and controls rendered separately.

The owner selected the Club design from a three-option generated collage. Its crest reuses the existing generated button material; Phosphor icons, clan names, counts, membership rows and invitation actions remain live app elements.
