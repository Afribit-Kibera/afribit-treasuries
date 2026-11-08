async (page) => {
  const s = __LOCAL_SESSION__,
    checks = [],
    errors = [];
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  const context = await page
    .context()
    .browser()
    .newContext({ viewport: { width: 390, height: 844 }, locale: "en-KE" });
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
  await p.goto("http://localhost:8415/");
  await p
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Activity", exact: true })
    .click();
  await p.locator(".ledger-row").first().waitFor();
  check(
    "Real monthly history rendered",
    (await p.locator(".ledger-row").count()) > 0,
  );
  check(
    "Future month disabled",
    await p
      .getByRole("button", { name: "Next month", exact: true })
      .isDisabled(),
  );
  const month = await p.getByLabel("Activity month").inputValue();
  await p.getByRole("button", { name: "Previous month", exact: true }).click();
  await p.getByText("No activity this month.", { exact: true }).waitFor();
  check("Previous month empty state", true);
  await p.getByRole("button", { name: "Next month", exact: true }).click();
  await p.locator(".ledger-row").first().waitFor();
  check(
    "Next month returns to current history",
    (await p.getByLabel("Activity month").inputValue()) === month,
  );
  // Only local API records are selected for the visual comparison; no invented events.
  const path = `**/api/clans/${s.clan_id}/activity?*`;
  const real = await (
    await p.request.get(
      `http://localhost:8415/api/clans/${s.clan_id}/activity?month=${month}&timezone=UTC&limit=50`,
    )
  ).json();
  const selected = [
    "grant_requested",
    "grant_disbursed",
    "treasury_settled",
    "member_joined",
  ].flatMap((event) =>
    real.items.filter((item) => item.event === event).slice(0, 1),
  );
  await p.route(path, (route) =>
    route.fulfill({ json: { ...real, items: selected, next_cursor: null } }),
  );
  await p
    .getByRole("button", { name: "Refresh activity", exact: true })
    .click();
  await p.locator(".ledger-row").first().waitFor();
  await p.locator(".ledger-amount").first().waitFor();
  check(
    "Request is clearly labeled",
    (await p
      .locator(".ledger-request-label")
      .getByText("Requested", { exact: true })
      .count()) > 0,
  );
  check(
    "Grant paid is money out",
    (await p.locator(".ledger-out").innerText()).includes("−"),
  );
  check(
    "Confirmed deposit is money in",
    (await p.locator(".ledger-in").innerText()).includes("+"),
  );
  check(
    "Member join has no invented amount",
    (await p
      .locator(".ledger-row")
      .filter({
        has: p.getByRole("heading", { name: "Member joined", exact: true }),
      })
      .locator(".ledger-amount")
      .count()) === 0,
  );
  for (const theme of ["dark", "light"]) {
    if (
      (await p.evaluate(() => document.documentElement.dataset.theme)) !== theme
    )
      await p
        .getByRole("button", {
          name:
            theme === "dark" ? "Switch to dark mode" : "Switch to light mode",
        })
        .click();
    for (const width of [320, 390, 430, 768, 1366]) {
      await p.setViewportSize({ width, height: 844 });
      check(
        theme + " ledger fits " + width,
        await p.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await p.setViewportSize({ width: 390, height: 844 });
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(300);
    await p.screenshot({
      path: "output/playwright/clans-activity-ledger-" + theme + ".png",
    });
  }
  await p.route(path, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "History temporarily unavailable" },
    }),
  );
  await p
    .getByRole("button", { name: "Refresh activity", exact: true })
    .click();
  await p.getByRole("alert").waitFor();
  check(
    "Load failure explains retry",
    await p.getByRole("button", { name: "Try again", exact: true }).isVisible(),
  );
  await p.unroute(path);
  await p.getByRole("button", { name: "Try again", exact: true }).click();
  await p.locator(".ledger-row").first().waitFor();
  check("Retry restores actual history", true);
  await p.route(path, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      json: {
        ...real,
        items: cursor ? selected.slice(1) : selected.slice(0, 2),
        next_cursor: cursor ? null : "local-pagination-check",
      },
    });
  });
  await p
    .getByRole("button", { name: "Refresh activity", exact: true })
    .click();
  await p
    .getByRole("button", { name: "Load more from this month", exact: true })
    .click();
  await p.locator(".ledger-end").waitFor();
  check(
    "Pagination appends without duplicates",
    (await p.locator(".ledger-row").count()) === selected.length,
  );
  await p.unroute(path);
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await p.route(path, async (route) => {
    await gate;
    await route.fulfill({
      json: { ...real, items: selected, next_cursor: null },
    });
  });
  await p
    .getByRole("button", { name: "Refresh activity", exact: true })
    .click();
  await p.getByRole("status").getByText("Loading this month").waitFor();
  check(
    "Loading state visible",
    await p
      .getByRole("button", { name: "Previous month", exact: true })
      .isDisabled(),
  );
  release();
  await p.locator(".ledger-row").first().waitFor();
  check("No browser errors", errors.length === 0);
  await context.close();
  return {
    checks,
    passed: checks.length,
    provider: "local test transport only",
    funds_sent: false,
  };
};
