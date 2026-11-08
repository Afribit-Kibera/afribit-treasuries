async (page) => {
  const s = __LOCAL_SESSION__,
    checks = [],
    errors = [];
  const check = (name, ok) => {
    if (!ok) throw new Error(name);
    checks.push(name);
  };
  const context = await page
    .context()
    .browser()
    .newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
  await context.addCookies([
    {
      name: s.cookie_name,
      value: s.owner,
      url: "http://localhost:8415",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const p = await context.newPage();
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto("http://localhost:8415");
  await p.evaluate(() => document.fonts.ready);
  for (const theme of ["dark", "light"]) {
    const toggle = p.getByRole("button", {
      name: theme === "light" ? "Switch to light mode" : "Switch to dark mode",
      exact: true,
    });
    if (await toggle.count()) await toggle.click();
    for (const tab of ["Home", "Clan", "Activity", "Profile"]) {
      await p.getByRole("button", { name: tab, exact: true }).click();
      await p.locator(".page-" + tab.toLowerCase()).waitFor();
      for (const width of [320, 390, 768, 1280]) {
        await p.setViewportSize({ width, height: 844 });
        await p.waitForFunction(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
          { timeout: 3000 },
        );
        check(theme + " " + tab + " fits " + width, true);
      }
      await p.setViewportSize({ width: 390, height: 844 });
    }
  }
  check(
    "Reduced motion removes screen animation",
    await p
      .locator(".profile-screens")
      .evaluate((el) => getComputedStyle(el).animationName === "none"),
  );
  await p.getByRole("button", { name: /^Country & currency/ }).click();
  check(
    "Profile section works after extraction",
    (await p.locator(".profile-screens>h2").innerText()) ===
      "Country & currency",
  );
  await p.getByRole("button", { name: "Home", exact: true }).click();
  await p.getByRole("button", { name: "Add money", exact: true }).click();
  check(
    "Setup inputs stay at least 16px",
    await p
      .locator("dialog input")
      .first()
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize) >= 16),
  );
  await p
    .getByRole("textbox", { name: "Amount in KES", exact: true })
    .fill("10");
  await p.getByRole("button", { name: "Check amount", exact: true }).click();
  await p.getByRole("heading", { name: /KES 10/ }).waitFor();
  check("Deposit amount gets a server currency quote", true);
  await p.getByRole("button", { name: "Change amount", exact: true }).click();
  await p
    .getByRole("combobox", { name: "Pay in", exact: true })
    .selectOption("SATS");
  await p
    .getByRole("textbox", { name: "Amount in sats", exact: true })
    .fill("999999999");
  await p
    .getByRole("button", { name: "Create payment request", exact: true })
    .click();
  await p.locator(".sheet-error").waitFor();
  check(
    "Rejected amount can be corrected",
    await p
      .getByRole("textbox", { name: "Amount in sats", exact: true })
      .isEditable(),
  );
  await p.getByRole("button", { name: "Close dialog", exact: true }).click();
  await p.locator("dialog").waitFor({ state: "detached" });
  const deposit = await p.evaluate(
    async (cid) =>
      (
        await (
          await fetch("/api/clans/" + cid + "?include_activity=false")
        ).json()
      ).deposits.find((d) => d.status === "settled"),
    s.clan_id,
  );
  const url = "**/api/clans/" + s.clan_id + "/deposits/" + deposit.id;
  await p.route(url, (route) =>
    route.fulfill({
      json: {
        ...deposit,
        status: "creating",
        bolt11: null,
        checkout_url: null,
        credited_sats: 0,
      },
    }),
  );
  await p.goto(
    "http://localhost:8415/?payment=" + deposit.id + "&clan=" + s.clan_id,
  );
  await p
    .getByRole("heading", { name: "Getting your request ready", exact: true })
    .waitFor();
  check(
    "Async provider preparation has a visible loader",
    (await p.locator(".payment-result .spin").count()) === 1,
  );
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-deposit-preparing.png",
  });
  await p.unroute(url);
  await p.getByRole("button", { name: "Check again", exact: true }).click();
  await p
    .getByRole("heading", { name: "Money received", exact: true })
    .waitFor();
  check("Status retry reaches verified completion", true);
  await p.getByRole("button", { name: "Done", exact: true }).click();
  await p.getByRole("button", { name: "Profile", exact: true }).click();
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-profile-menu.png",
  });
  check(
    "Heading font is Sora",
    await p
      .locator(".profile-identity h2")
      .evaluate((el) => getComputedStyle(el).fontFamily.includes("Sora")),
  );
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await p.getByRole("button", { name: "Home", exact: true }).click();
  await p.locator(".clan-home").waitFor();
  check(
    "Changing screens returns to the top",
    await p.evaluate(() => scrollY === 0),
  );
  check(
    "Money font uses tabular figures",
    await p
      .locator(".home-balance-number")
      .evaluate(
        (el) =>
          getComputedStyle(el).fontFamily.includes("Space Grotesk") &&
          getComputedStyle(el).fontVariantNumeric.includes("tabular-nums"),
      ),
  );
  check(
    "Background uses compressed artwork",
    await p
      .locator(".background-art")
      .evaluate((el) => getComputedStyle(el).backgroundImage.includes(".webp")),
  );
  await context.close();
  return { checks, errors, passed: checks.length, real_funds_moved: false };
};
