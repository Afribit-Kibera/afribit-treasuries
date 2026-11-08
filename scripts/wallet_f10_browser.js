async (page) => {
  const checks = [];
  const check = (n, v) => {
    if (!v) throw Error(n);
    checks.push(n);
  };
  const button = (n) => page.getByRole("button", { name: n, exact: true });
  const dialog = () => page.getByRole("dialog");
  const close = async () => {
    await dialog().getByRole("button", { name: /Close/ }).click();
    await dialog().waitFor({ state: "hidden" });
  };
  const unlock = async () => {
    await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
    await button("Unlock signing key").click();
  };
  const fits = async (name) => {
    for (const theme of ["dark", "light"]) {
      await page.evaluate((t) => (document.documentElement.dataset.theme = t), theme);
      for (const width of [320, 390, 430, 768, 1366]) {
        await page.setViewportSize({ width, height: 844 });
        check(
          name + " " + theme + " " + width,
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        );
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(320);
      await page.screenshot({ path: "output/playwright/clan-wallet-" + name + "-" + theme + ".png" });
    }
  };
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://localhost:5182/__wallet_preview");
  await button("Use test signing key").click();
  await button("Compare wallet code").waitFor();
  await page.getByLabel("Wallet status", { exact: true }).selectOption("active");
  await button("Check wallet code on this phone").click();
  await unlock();
  await button("All codes match").click();
  await dialog().waitFor({ state: "hidden" });
  await page.evaluate(() => {
    const original = window.fetch;
    window.__signed = 0;
    window.fetch = (i, o) => {
      if (String(i).endsWith("/signature")) window.__signed++;
      return original(i, o);
    };
  });

  // A move to a wallet this phone hasn't compared is never signable.
  await button("Show moved wallet fixture").click();
  await button("Review wallet move · generation 1").click();
  await page.getByText("Compare the new wallet's code on this phone first.", { exact: true }).waitFor();
  check("Move without the new wallet's check is refused", true);
  check("No sign button without the new wallet's check", !(await button("Sign payout").count()));
  await close();

  // Refresh of the current wallet reviews and signs with the saved check.
  await button("Show wallet refresh fixture").click();
  await button("Review wallet refresh · generation 1").click();
  await button("Sign payout").waitFor();
  const refreshText = await dialog().innerText();
  check("Refresh explains the recovery wait", refreshText.includes("6-month recovery wait starts again"));
  check("Refresh shows who pays the fee", refreshText.includes("The clan"));
  await fits("refresh");
  await close();

  // Start, then cancel, a new wallet.
  await button("Start a new clan wallet").click();
  await dialog().getByLabel("Why does the clan need a new wallet?").selectOption("stolen_phone");
  await button("Start wallet setup").click();
  await page.getByText("New clan wallet (generation 2)", { exact: true }).waitFor();
  check("Started wallet shows its reason", (await page.innerText("body")).includes("Stolen phone"));
  await button("Stop setting up").click();
  await button("Yes, stop setting up").click();
  await button("Start a new clan wallet").waitFor();
  check("Cancelled setup returns to the current wallet", !(await page.getByText("New clan wallet (generation 2)").count()));

  // Set up the new wallet with the current key, then compare it.
  await button("Show new wallet fixture").click();
  await page.getByText("New clan wallet (generation 2)", { exact: true }).waitFor();
  const nextText = await page.innerText("body");
  check("New wallet shows who started it", nextText.includes("Started by Grace"));
  check("New wallet shows signatory progress", nextText.includes("Waiting"));
  await fits("next");
  await button("Use my signing key again").click();
  await button("Use my current key").waitFor();
  check("Reuse explains keeping the current key", (await dialog().innerText()).includes("Keep your current key if you still have it."));
  await button("Use my current key").click();
  await unlock();
  await button("Add my signing key").click();
  await dialog().waitFor({ state: "hidden" });
  await button("Compare new wallet code").click();
  await unlock();
  await button("All codes match").click();
  await dialog().waitFor({ state: "hidden" });
  const records = await page.evaluate(() =>
    Object.keys(localStorage).filter((k) => k.startsWith("clans-public-wallet-check-")).sort(),
  );
  check(
    "Both generations' checks are kept",
    records.includes("clans-public-wallet-check-v2:preview:1") &&
      records.includes("clans-public-wallet-check-v2:preview:2"),
  );
  const movedText = await page.innerText("body");
  check("Old wallet balance shown", movedText.includes("Old wallet (generation 1): 100,000 sats still to move"));
  check("Backup reminder keeps the old one", movedText.includes("Keep your old backup too"));

  // The move now reviews against both saved checks, and signs.
  await button("Review wallet move · generation 1").click();
  await button("Sign payout").waitFor();
  const moveText = await dialog().innerText();
  check("Move names the new wallet", moveText.includes("Move to the clan's new wallet (generation 2)"));
  check("Move shows the phone-reviewed amount", moveText.includes("Money moved after fee"));
  await fits("move");
  await button("Sign payout").click();
  await unlock();
  await page.getByText("Waiting for Afribit", { exact: true }).first().waitFor();
  check("Move signature sent once", (await page.evaluate(() => window.__signed)) === 1);
  check("No browser runtime errors", errors.length === 0);
  return { passed: checks.length, checks };
};
