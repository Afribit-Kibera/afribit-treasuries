async (page) => {
  const checks = [];
  await page.goto("http://localhost:5182/__wallet_preview");
  for (const status of [
    "not_started",
    "collecting_keys",
    "confirming",
    "active",
    "retired",
  ]) {
    await page
      .getByLabel("Wallet status", { exact: true })
      .selectOption(status);
    await page
      .getByRole("button", { name: "Refresh wallet", exact: true })
      .waitFor();
    for (const theme of ["dark", "light"]) {
      await page.evaluate(
        (v) => (document.documentElement.dataset.theme = v),
        theme,
      );
      for (const width of [320, 390, 430, 768, 1366]) {
        await page.setViewportSize({ width, height: 844 });
        if (
          !(await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ))
        )
          throw Error(status + " overflows " + width);
        checks.push(status + " " + theme + " " + width);
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(300);
      await page.screenshot({
        path: "output/playwright/clan-wallet-" + status + "-" + theme + ".png",
      });
    }
  }
  return { passed: checks.length, checks };
};
