async (page) => {
  const checks = [];
  const check = (n, v) => {
    if (!v) throw Error(n);
    checks.push(n);
  };
  const button = (n) => page.getByRole("button", { name: n, exact: true });
  const close = async () => {
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /Close/ })
      .click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  };
  await page.goto("http://localhost:5182/__wallet_preview");
  await button("Use test signing key").click();
  await page.getByRole("button", { name: "Compare wallet code", exact: true }).waitFor();
  await page
    .getByLabel("Wallet status", { exact: true })
    .selectOption("active");
  await button("Check wallet code on this phone").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await button("All codes match").click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  await page.evaluate(() => {
    const original = window.fetch;
    window.__signed = 0;
    window.__addressPosts = 0;
    window.fetch = (i, o) => {
      if (String(i).endsWith("/signature")) {
        window.__signed++;
        const body = JSON.parse(o.body);
        window.__onlySignedCopy =
          Object.keys(body).join(",") === "psbt" &&
          body.psbt.startsWith("cHNidP");
      }
      if (String(i).endsWith("/payout-address")) window.__addressPosts++;
      return original(i, o);
    };
  });
  await button("Review test payout").click();
  await button("Sign payout").waitFor();
  check(
    "Valid payment passes phone review",
    await page.getByText("Checked on this phone", { exact: true }).isVisible(),
  );
  check(
    "Fee and beneficiary amount displayed",
    (await page.getByRole("dialog").innerText()).includes("39,546") &&
      (await page.getByRole("dialog").innerText()).includes("454"),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Payout " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-payout-" + theme + ".png",
    });
  }
  await button("Sign payout").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await page
    .getByText("2 of 2 signatories, then Afribit: Juma, Amina.", {
      exact: true,
    })
    .waitFor();
  check(
    "Only signed payment sent",
    await page.evaluate(() => window.__signed === 1 && window.__onlySignedCopy),
  );
  await close();
  await page.getByLabel("Payout case", { exact: true }).selectOption("normal");
  await button("Review test payout").click();
  await button("Sign payout").click();
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = async (i, o) => {
      const r = await original(i, o);
      if (String(i).endsWith("/wallet/payouts/fixture-payout") && !o?.body) {
        const d = await r.json();
        return Response.json({ ...d, status: "replaced" });
      }
      return r;
    };
  });
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "The payment changed" })
    .waitFor();
  check(
    "A replaced payment cannot send a signature",
    await page.evaluate(() => window.__signed === 1),
  );
  await close();
  for (const mode of ["tampered", "bad-fee"]) {
    await page.getByLabel("Payout case", { exact: true }).selectOption(mode);
    await button("Review test payout").click();
    await page
      .getByText("Stop. Do not use this wallet.", { exact: true })
      .waitFor();
    check(mode + " cannot sign", (await button("Sign payout").count()) === 0);
    await close();
  }
  for (const status of [
    "awaiting_oversight",
    "broadcasting",
    "broadcast",
    "confirmed",
    "replaced",
    "expired",
  ]) {
    await page.getByLabel("Payout case", { exact: true }).selectOption(status);
    await button("Review test payout").click();
    await page.getByLabel("Clan wallet payout").waitFor();
    await page.getByText("Checked on this phone", { exact: true }).waitFor();
    check(
      status + " has no sign button",
      (await button("Sign payout").count()) === 0,
    );
    await close();
  }
  await page.getByLabel("Payout case", { exact: true }).selectOption("normal");
  await button("Add test receiving address").click();
  const address = page.getByLabel("Bitcoin address", { exact: true });
  await address.fill("not-an-address");
  await button("Check receiving amount").click();
  await page.getByRole("alert").waitFor();
  check(
    "Invalid address refused locally",
    await page.evaluate(() => window.__addressPosts === 0),
  );
  await address.fill("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4");
  await button("Check receiving amount").click();
  check(
    "Mainnet address refused locally",
    await page.evaluate(() => window.__addressPosts === 0),
  );
  await address.fill("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx");
  await button("Check receiving amount").click();
  await button("Use this Bitcoin address").waitFor();
  check(
    "Quote does not save an address",
    await page.evaluate(() => window.__addressPosts === 0),
  );
  await button("Use this Bitcoin address").click();
  await page
    .getByText(
      "Address added. Your signatories still need to check and sign the payment.",
      { exact: true },
    )
    .waitFor();
  check(
    "Estimated received amount shown",
    (await page.getByRole("dialog").innerText()).includes("39,546"),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Receiving " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-receiving-" + theme + ".png",
    });
  }
  await close();
  await page
    .getByLabel("Payout case", { exact: true })
    .selectOption("bad-estimate");
  await button("Add test receiving address").click();
  await address.fill("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx");
  await button("Check receiving amount").click();
  await page
    .getByText("Stop. Do not use this wallet.", { exact: true })
    .waitFor();
  check(
    "Changed estimate stops flow",
    (await button("Use this Bitcoin address").count()) === 0,
  );
  return { passed: checks.length, checks };
};
