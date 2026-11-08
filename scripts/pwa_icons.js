// Mechanical browser rasterization of the existing brand mark; no logo redesign.
async (page) => {
  await page.setContent('<!doctype html><html><head><style>html,body{margin:0;width:100%;height:100%;background:#0c0d0c}body{display:flex;align-items:center;justify-content:center}img{width:65%;height:65%;object-fit:contain}</style></head><body><img alt="AfriBit" src="http://127.0.0.1:5177/assets/afribit-mark.png"></body></html>')
  await page.locator('img').evaluate(image => image.decode())
  for (const size of [192, 512, 180]) {
    await page.setViewportSize({ width: size, height: size })
    await page.screenshot({ path: `output/playwright/clans-icon-${size}.png`, scale: 'css' })
  }
  return { icons: [192, 512, 180], source: 'Existing AfriBit logo; unchanged artwork on charcoal', funds_moved: false }
}
