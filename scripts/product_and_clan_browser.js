async (page) => {
  const checks = [],
    errors = [],
    s = __LOCAL_SESSION__;
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  const browser = page.context().browser();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const p = await context.newPage();
  p.on("pageerror", (e) => errors.push(e.message));
  const apiRequests = [];
  p.on("request", (r) => {
    if (r.url().includes("/api/")) apiRequests.push(r.url());
  });
  await p.goto("http://localhost:8415/about/");
  await p.getByRole("heading", { level: 1 }).waitFor();
  check(
    "Public page identifies Clans as part of Afribit Wallet",
    await p
      .getByText("A feature of Afribit Wallet", { exact: true })
      .isVisible(),
  );
  for (const theme of ["dark", "light"]) {
    if (
      (await p.evaluate(() => document.documentElement.dataset.theme)) !== theme
    )
      await p
        .getByRole("button", {
          name:
            theme === "light" ? "Switch to light mode" : "Switch to dark mode",
        })
        .click();
    for (const width of [320, 390, 430, 768, 1366]) {
      await p.setViewportSize({ width, height: 900 });
      check(
        theme + " public page fits " + width,
        await p.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await p.setViewportSize({ width: 390, height: 844 });
    await p.evaluate(() => document.fonts.ready);
    await p.screenshot({
      path: "output/playwright/clans-product-" + theme + "-mobile.png",
      fullPage: false,
    });
  }
  await p.getByRole("link", { name: "See how it works", exact: true }).click();
  check(
    "How it works scrolls to the guide",
    new URL(p.url()).hash === "#how-it-works",
  );
  const question = p
    .locator("summary")
    .filter({ hasText: "Where does a grant go?" });
  await question.focus();
  await p.keyboard.press("Enter");
  check(
    "Destination explanation opens from keyboard",
    await question
      .locator("..")
      .getByText(/The member supplies a Lightning payment request/)
      .isVisible(),
  );
  check("Public page makes no account API requests", apiRequests.length === 0);
  await p.setViewportSize({ width: 1366, height: 900 });
  await p.locator(".product-steps").scrollIntoViewIfNeeded();
  await p.locator(".product-faq").scrollIntoViewIfNeeded();
  await p.locator(".product-final").scrollIntoViewIfNeeded();
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.screenshot({
    path: "output/playwright/clans-product-desktop.png",
    fullPage: true,
  });
  const reduced = await browser.newContext({
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  });
  const r = await reduced.newPage();
  await r.goto("http://localhost:8415/about/");
  check(
    "Reduced motion disables floating artwork",
    await r
      .locator(".product-paw")
      .first()
      .evaluate((el) => getComputedStyle(el).animationName === "none"),
  );
  await reduced.close();
  await context.addCookies([
    {
      name: s.cookie_name,
      value: s.owner,
      url: "http://localhost:8415",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await p.goto("http://localhost:8415/");
  await p.getByRole("button", { name: "Clan", exact: true }).click();
  for (const theme of ["dark", "light"]) {
    if (
      (await p.evaluate(() => document.documentElement.dataset.theme)) !== theme
    )
      await p
        .getByRole("button", {
          name:
            theme === "light" ? "Switch to light mode" : "Switch to dark mode",
        })
        .click();
    for (const width of [320, 390, 430, 768]) {
      await p.setViewportSize({ width, height: 844 });
      const rule = p.getByRole("region", { name: "Payment approvals" });
      await rule.scrollIntoViewIfNeeded();
      await rule.evaluate((el) => el.scrollIntoView({ block: "end" }));
      const note = await rule.boundingBox();
      const nav = await p.locator(".bottom-nav").boundingBox();
      check(
        theme + " approval note clears navigation at " + width,
        note !== null && nav !== null && note.y + note.height <= nav.y - 12,
      );
      check(
        theme + " clan approvals fit " + width,
        await p.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      check(
        theme + " approval explanation is present at " + width,
        await rule.getByText(/Members vote on a grant/).isVisible(),
      );
    }
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator(".club-rule").scrollIntoViewIfNeeded();
    await p
      .locator(".club-rule")
      .evaluate((el) => el.scrollIntoView({ block: "end" }));
    await p.screenshot({
      path: "output/playwright/clans-approval-" + theme + ".png",
    });
  }
  await p.getByRole("button", { name: "Activity", exact: true }).click();
  await p.locator(".monthly-activity .ledger-row").first().waitFor();
  if (
    (await p.evaluate(() => document.documentElement.dataset.theme)) !== "dark"
  )
    await p.getByRole("button", { name: "Switch to dark mode" }).click();
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.screenshot({ path: "output/playwright/clans-activity-current.png" });
  check("No browser runtime errors", errors.length === 0);
  await context.close();
  return {
    checks,
    passed: checks.length,
    provider: "isolated local test transport",
    funds_sent: false,
  };
};
