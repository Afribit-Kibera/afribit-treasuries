async (page) => {
  await page.goto('http://127.0.0.1:5177/')
  await page.getByText('KES 42,500', { exact: true }).waitFor()
  const checks = []
  const chooseTheme = async theme => {
    const current = await page.locator('html').getAttribute('data-theme')
    if (current !== theme) await page.getByRole('button', { name: `Switch to ${theme} mode` }).click()
    await page.evaluate(() => document.fonts.ready)
    await page.evaluate(() => Promise.all(document.getAnimations().filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {}))))
  }
  for (const [width, height, name] of [[390, 844, 'mobile'], [1366, 900, 'desktop']]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['dark', 'light']) {
      await chooseTheme(theme)
      await page.screenshot({ path: `output/playwright/clans-${name}-${theme}.png`, scale: 'css', animations: 'disabled' })
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`Overflow at ${width}/${theme}`)
      checks.push(`${name} ${theme}: rendered without overflow`)
    }
  }
  for (const width of [320, 360, 768]) {
    await page.setViewportSize({ width, height: 844 })
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`Overflow at ${width}`)
    checks.push(`${width}px: no horizontal overflow`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.screenshot({ path: 'output/playwright/clans-grant-review.png', scale: 'css' })
  const activeInDialog = await page.evaluate(() => !!document.querySelector('dialog')?.contains(document.activeElement))
  if (!activeInDialog) throw new Error('Focus did not enter modal')
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  checks.push('Dialog focus and Escape dismissal work')
  const manifest = await page.evaluate(async () => {
    const response = await fetch('/manifest.webmanifest')
    const manifest = await response.json()
    const icons = await Promise.all(manifest.icons.map(async icon => {
      const image = new Image(); image.src = icon.src; await image.decode()
      return { declared: icon.sizes, actual: `${image.naturalWidth}x${image.naturalHeight}` }
    }))
    return { display: manifest.display, icons }
  })
  if (manifest.display !== 'standalone' || manifest.icons.some(icon => icon.declared !== icon.actual)) throw new Error('Invalid PWA icon metadata')
  checks.push('Standalone manifest and 192/512 icons verified')
  // Development has no service worker; load modal font faces before going offline.
  await page.evaluate(() => Promise.all([
    document.fonts.load('600 20px "Cormorant Garamond"'),
    document.fonts.load('700 20px "Cormorant Garamond"'),
    document.fonts.load('italic 600 20px "Cormorant Garamond"'),
  ]))
  await page.context().setOffline(true)
  await page.getByText('You’re offline. Your treasury is read-only until you reconnect.', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Add a contribution, request, repayment or clan', exact: true }).click()
  await page.getByRole('button', { name: /^Contribute/ }).click()
  if (!await page.getByRole('button', { name: 'Record demo contribution', exact: true }).isDisabled()) throw new Error('Offline write was enabled')
  await page.context().setOffline(false)
  await page.getByRole('button', { name: 'Close dialog' }).click()
  checks.push('Offline state disables treasury mutations')
  const cdp = await page.context().newCDPSession(page)
  const installation = await cdp.send('Page.getInstallabilityErrors')
  await cdp.detach()
  await chooseTheme('dark')
  return { result: 'passed', checks, manifest, installation, real_funds_moved: false }
}
