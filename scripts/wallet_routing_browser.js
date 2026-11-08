async (page) => {
  const checks = [];
  const check = (n, v) => {
    if (!v) throw Error(n);
    checks.push(n);
  };
  const button = (n) => page.getByRole("button", { name: n, exact: true });
  const close = async () => {
    await button("Close dialog").click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  };
  await page.goto("http://localhost:5182/__wallet_preview");
  for (const mode of ["inactive", "disabled", "active"]) {
    if (mode === "active")
      await page
        .getByLabel("Wallet status", { exact: true })
        .selectOption("active");
    if (mode === "disabled")
      await page.getByLabel("Safety case").selectOption("disabled");
    await button("Test grant routing").click();
    if (mode === "active") {
      await page
        .getByRole("heading", { name: "Your Bitcoin receiving address" })
        .waitFor();
      check(
        "Active wallet replaces invoice entry",
        (await page.getByLabel("Payment request from your wallet").count()) ===
          0,
      );
    } else {
      await page.getByLabel("Payment request from your wallet").waitFor();
      check(
        mode + " retains Lightning grant flow",
        (await page.getByLabel("Bitcoin address", { exact: true }).count()) ===
          0,
      );
    }
    await close();
    await button("Test deposit routing").click();
    if (mode === "active") {
      await page.getByLabel("Amount (sats)", { exact: true }).waitFor();
      check(
        "Active wallet has checked Bitcoin deposit flow",
        await button("Get payment address").isVisible(),
      );
    } else {
      await page.getByLabel("Pay in").waitFor();
      check(
        mode + " retains Lightning deposit flow",
        (await button("Get payment address").count()) === 0,
      );
    }
    await close();
  }
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (i, o) =>
      String(i).endsWith("/preview/wallet")
        ? Promise.resolve(
            Response.json(
              { detail: "Cannot check the wallet" },
              { status: 503 },
            ),
          )
        : original(i, o);
  });
  await button("Test grant routing").click();
  await page.getByRole("alert").waitFor();
  check(
    "Unknown wallet never falls back to invoice entry",
    (await page.getByLabel("Payment request from your wallet").count()) === 0 &&
      (await button("Try again").isVisible()),
  );
  await close();
  await button("Test deposit routing").click();
  await page.getByRole("alert").waitFor();
  check(
    "Unknown wallet never falls back to Lightning deposits",
    (await page.getByLabel("Pay in").count()) === 0 &&
      (await button("Try again").isVisible()),
  );
  return { passed: checks.length, checks };
};
