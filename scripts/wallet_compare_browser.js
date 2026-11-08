async (page) => {
  const checks = [],
    errors = [];
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  page.on("pageerror", (e) => errors.push(e.message));
  async function start(safety) {
    await page.goto("http://localhost:5182/__wallet_preview");
    await page
      .getByRole("button", { name: "Use test signing key", exact: true })
      .click();
  await page.getByRole("button", { name: "Compare wallet code", exact: true }).waitFor();
    await page.getByLabel("Safety case").selectOption(safety);
    await page
      .getByRole("button", { name: "Compare wallet code", exact: true })
      .click();
    await page.getByLabel("Your signing key PIN", { exact: true }).waitFor();
  }
  async function unlock(pin = "123456") {
    await page.getByLabel("Your signing key PIN", { exact: true }).fill(pin);
    await page
      .getByRole("button", { name: "Unlock signing key", exact: true })
      .click();
  }
  await start("server-code");
  await unlock("111111");
  check(
    "Wrong PIN cannot reveal wallet code",
    (await page.getByLabel("Phone wallet code").count()) === 0,
  );
  await unlock();
  await page.getByLabel("Phone wallet code").waitFor();
  const own = (await page.getByLabel("Phone wallet code").innerText()).replace(
    /\s/g,
    "",
  );
  check(
    "Displayed code is computed on phone",
    own.length === 8 && own !== "xxxxxxxx",
  );
  await page.evaluate(() => {
    const fetch = window.fetch;
    window.__confirmed = null;
    window.fetch = (input, init) => {
      if (String(input).endsWith("/confirm"))
        window.__confirmed = JSON.parse(String(init.body)).wallet_code;
      return fetch(input, init);
    };
  });
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (v) => (document.documentElement.dataset.theme = v),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        theme + " wallet code fits " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    await page.screenshot({
      path: "output/playwright/clan-wallet-code-" + theme + ".png",
    });
  }
  await page
    .getByRole("button", { name: "All codes match", exact: true })
    .click();
  await page.getByText("Clan wallet ready", { exact: true }).waitFor();
  check(
    "Only own code is submitted",
    await page.evaluate((code) => window.__confirmed === code, own),
  );
  check(
    "Saved wallet check is public only",
    await page.evaluate(() => {
      const v = JSON.parse(
        localStorage.getItem("clans-public-wallet-check-v2:preview:1"),
      );
      return (
        Object.keys(v).sort().join() === "code,generation,key,policy" &&
        v.key.includes("tpub")
      );
    }),
  );
  for (const safety of [
    "missing-key",
    "key-not-in-wallet",
    "confirm-refused",
  ]) {
    await start(safety);
    await unlock();
    if (safety === "confirm-refused") {
      await page.getByLabel("Phone wallet code").waitFor();
      await page
        .getByRole("button", { name: "All codes match", exact: true })
        .click();
    }
    await page
      .getByText("Stop. Do not use this wallet.", { exact: true })
      .waitFor();
    check(
      safety + " fails closed",
      (await page
        .getByRole("button", { name: "All codes match", exact: true })
        .count()) === 0,
    );
  }
  await start("normal");
  await unlock();
  await page
    .getByRole("button", { name: "Codes are different", exact: true })
    .click();
  check(
    "Member mismatch stops confirmation",
    (await page
      .getByRole("button", { name: "All codes match", exact: true })
      .count()) === 0,
  );
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  await page.getByLabel("Safety case").selectOption("member");
  check(
    "Member sees read-only status",
    (await page
      .getByRole("button", { name: "Compare wallet code", exact: true })
      .count()) === 0,
  );
  await page.getByLabel("Safety case").selectOption("disabled");
  check(
    "Disabled feature is hidden",
    (await page
      .getByRole("region", { name: "Clan wallet", exact: true })
      .count()) === 0,
  );
  check("No runtime errors", errors.length === 0);
  return { checks, passed: checks.length, network: "local fixtures only" };
};
