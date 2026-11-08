async (page) => {
  const s = __LOCAL_SESSION__,
    checks = [];
  const context = await page
    .context()
    .browser()
    .newContext({ viewport: { width: 390, height: 844 } });
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
  const errors = [];
  p.on("pageerror", (error) => errors.push(error.message));
  await p.goto("http://localhost:8415");
  let polls = 0;
  await p.route("**/api/clans/" + s.clan_id + "/deposits/*", async (route) => {
    polls++;
    await route.fulfill({
      json: {
        id: "held-request",
        amount_sats: 100,
        credited_sats: 0,
        status: "review_required",
        bolt11: "must-not-be-shown",
        checkout_url: "https://example.invalid",
      },
    });
  });
  await p.getByRole("button", { name: "Add money", exact: true }).click();
  await p
    .getByRole("combobox", { name: "Pay in", exact: true })
    .selectOption("SATS");
  await p
    .getByRole("textbox", { name: "Amount in sats", exact: true })
    .fill("100");
  await p
    .getByRole("button", { name: "Create payment request", exact: true })
    .click();
  await p
    .getByRole("heading", { name: "This request needs a check", exact: true })
    .waitFor();
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  check(
    "Held request explains that members must not pay",
    await p.getByText(/Please do not pay this request/).isVisible(),
  );
  check(
    "No held invoice or wallet link is displayed",
    (await p.locator(".payment-qr, .wallet-picker").count()) === 0 &&
      !(await p.locator("body").innerText()).includes("must-not-be-shown"),
  );
  for (const width of [320, 390, 430]) {
    await p.setViewportSize({ width, height: 844 });
    check(
      "No horizontal overflow at " + width,
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
  }
  const before = polls;
  await p.waitForTimeout(5500);
  check("Held requests stop automatic polling", polls === before);
  await p.screenshot({
    path: "output/playwright/receiving-held-mobile.png",
    animations: "disabled",
  });
  await p.getByRole("button", { name: "Close", exact: true }).click();
  check(
    "Held screen closes",
    await p.getByRole("button", { name: "Add money", exact: true }).isVisible(),
  );
  check("No browser errors", errors.length === 0);
  await context.close();
  return {
    checks,
    passed: checks.length,
    provider: "isolated test transport only",
    real_funds_moved: false,
  };
};
