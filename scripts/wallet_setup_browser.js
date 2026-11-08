async (page) => {
  const checks = [],
    errors = [],
    sent = [];
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.method() === "POST")
      sent.push({ url: r.url(), body: r.postData() || "" });
  });
  await page.goto("http://localhost:5182/__wallet_preview");
  await page
    .getByRole("button", { name: "Create my signing key", exact: true })
    .waitFor();
  await page.evaluate(() => {
    const original = window.fetch;
    window.__walletCalls = [];
    window.fetch = (input, init) => {
      if (init?.method === "POST")
        window.__walletCalls.push({ body: String(init.body) });
      return original(input, init);
    };
  });
  await page
    .getByRole("button", { name: "Create my signing key", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Create my signing key", exact: true })
    .click();
  const words = await page.locator(".wallet-words li").allTextContents();
  const values = words.map((w) => w.replace(/^\s*\d+\s*/, "").trim());
  check(
    "Twelve words displayed only locally",
    values.length === 12 && sent.length === 0,
  );
  await page
    .getByRole("button", { name: "I wrote them down", exact: true })
    .click();
  const fields = page.locator(".sheet input");
  for (let i = 0; i < 3; i++) {
    const label = await fields.nth(i).locator("..").innerText();
    const position = Number(label.match(/\d+/)[0]);
    await fields.nth(i).fill(values[position - 1]);
  }
  await page
    .getByRole("button", { name: "Check my words", exact: true })
    .click();
  check(
    "Full words removed before protection",
    (await page.locator(".wallet-words").count()) === 0,
  );
  await page
    .getByLabel("Choose a signing key PIN", { exact: true })
    .fill("123456");
  await page.getByLabel("Enter the PIN again", { exact: true }).fill("123457");
  await page
    .getByRole("button", { name: "Protect with a PIN", exact: true })
    .click();
  check(
    "Mismatched PIN refused",
    (await page.getByRole("alert").isVisible()) && sent.length === 0,
  );
  await page.getByLabel("Enter the PIN again", { exact: true }).fill("123456");
  await page
    .getByRole("button", { name: "Protect with a PIN", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add my signing key", exact: true })
    .waitFor();
  for (const width of [320, 390, 430, 768, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    check(
      "Saved-key screen fits " + width,
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "output/playwright/clan-wallet-key-saved-dark.png",
  });
  await page.evaluate(() => (document.documentElement.dataset.theme = "light"));
  await page.waitForTimeout(350);
  await page.screenshot({
    path: "output/playwright/clan-wallet-key-saved-light.png",
  });
  await page
    .getByRole("button", { name: "Add my signing key", exact: true })
    .click();
  await page.getByText("Key added", { exact: true }).waitFor();
  const audit = await page.evaluate((words) => {
    const calls = window.__walletCalls;
    const result = {
      count: calls.length,
      publicOnly: calls.every(
        (r) =>
          Object.keys(JSON.parse(r.body)).join() === "key" &&
          JSON.parse(r.body).key.includes("tpub"),
      ),
      leaks: calls.some(
        (r) =>
          words.some((w) => r.body.includes('"' + w + '"')) ||
          r.body.includes("123456"),
      ),
    };
    delete window.__walletCalls;
    return result;
  }, values);
  check("Only public key registered", audit.count === 1 && audit.publicOnly);
  check("Words and PIN never transmitted", !audit.leaks);
  check("No runtime errors", errors.length === 0);
  values.fill("");
  words.fill("");
  return {
    checks,
    passed: checks.length,
    secrets_in_results: false,
    network: "local preview only",
  };
};
