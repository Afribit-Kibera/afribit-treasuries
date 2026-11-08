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
  await button("Test contribution").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page
    .getByRole("img", { name: "Bitcoin payment request for 10000 sats" })
    .waitFor();
  check(
    "Verified contribution has QR",
    (await page.getByRole("dialog").locator("img.deposit-qr").count()) === 1,
  );
  check(
    "Exact Bitcoin amount in wallet link",
    (
      await page
        .getByRole("link", { name: "Open Bitcoin wallet" })
        .getAttribute("href")
    ).endsWith("?amount=0.00010000"),
  );
  await button("Copy Bitcoin address").click();
  await page.getByText("Bitcoin address copied", { exact: true }).waitFor();
  check("Copy gives confirmation", true);
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Deposit " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-deposit-" + theme + ".png",
    });
  }
  check(
    "Unconfirmed deposit waits",
    await page
      .getByRole("status")
      .filter({ hasText: "Waiting for the network" })
      .isVisible(),
  );
  await page.evaluate(() =>
    window.dispatchEvent(new Event("wallet-preview-confirm")),
  );
  await button("Check payment status").click();
  await page.getByRole("status").filter({ hasText: "Received" }).waitFor();
  check(
    "Fixture confirmation shows received",
    (await page.getByRole("dialog").locator("img.deposit-qr").count()) === 0,
  );
  await close();
  for (const mode of ["tampered", "wrong-grant"]) {
    await page.getByLabel("Deposit case", { exact: true }).selectOption(mode);
    await button("Test repayment").click();
    await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
    await button("Get payment address").click();
    await page
      .getByText("Stop. Do not use this wallet.", { exact: true })
      .waitFor();
    check(
      mode + " never shows QR or copy",
      (await page.getByRole("dialog").locator("img.deposit-qr").count()) ===
        0 && (await button("Copy Bitcoin address").count()) === 0,
    );
    await close();
  }
  await page.getByLabel("Deposit case", { exact: true }).selectOption("normal");
  await button("Test repayment").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("3000");
  check(
    "Small repayment has fee advice",
    await page.getByText(/For less than 5,000 sats/).isVisible(),
  );
  await button("Get payment address").click();
  await page
    .getByRole("img", { name: "Bitcoin payment request for 3000 sats" })
    .waitFor();
  check("Grant-bound repayment passes", true);
  await close();
  await page.getByLabel("Deposit case", { exact: true }).selectOption("till");
  await button("Test contribution").click();
  await button("Pay with Lightning").waitFor();
  check("Lightning offered only when available", true);
  await close();
  await page
    .getByLabel("Deposit case", { exact: true })
    .selectOption("failure");
  await button("Test contribution").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "Connection lost" })
    .waitFor();
  check(
    "Address failure allows retry without QR",
    (await button("Get payment address").isEnabled()) &&
      (await page.getByRole("dialog").locator("img.deposit-qr").count()) === 0,
  );
  await close();
  await page.evaluate(() => {
    window.__restorePosts = 0;
    const original = window.fetch;
    window.fetch = (i, o) => {
      if (o?.method === "POST") window.__restorePosts++;
      return original(i, o);
    };
  });
  await button("I have a new phone").click();
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Empty restore " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-restore-empty-" + theme + ".png",
    });
  }
  const wrong = await page.evaluate(async () => {
    const f = await import("/src/wallet-fixtures.ts");
    return f.fixtureWords(5).split(" ");
  });
  for (let i = 0; i < 12; i++)
    await page.getByLabel("Word " + (i + 1), { exact: true }).fill(wrong[i]);
  await button("Check backup words").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "These words are for a different key" })
    .waitFor();
  check(
    "Wrong backup refused before protection",
    (await page
      .getByLabel("Choose a signing key PIN", { exact: true })
      .count()) === 0,
  );
  const right = await page.evaluate(async () => {
    const f = await import("/src/wallet-fixtures.ts");
    return f.fixtureWords(2).split(" ");
  });
  for (let i = 0; i < 12; i++)
    await page.getByLabel("Word " + (i + 1), { exact: true }).fill(right[i]);
  await button("Check backup words").click();
  await page.getByLabel("Choose a signing key PIN", { exact: true }).waitFor();
  check(
    "Backup fields removed before protection",
    (await page.getByLabel("Word 1", { exact: true }).count()) === 0,
  );
  await page
    .getByLabel("Choose a signing key PIN", { exact: true })
    .fill("654321");
  await page.getByLabel("Enter the PIN again", { exact: true }).fill("654321");
  await button("Protect with a PIN").click();
  await page
    .getByRole("heading", { name: "Signing key restored", exact: true })
    .waitFor();
  check(
    "Restore makes no POST",
    await page.evaluate(() => window.__restorePosts === 0),
  );
  check(
    "Restored key opens with new protection",
    await page.evaluate(async () => {
      const { vaultStore } = await import("/src/vault-access.ts");
      const v = await vaultStore();
      const f = await import("/src/wallet-fixtures.ts");
      return (
        (await v.openVault("preview", { kind: "pin", pin: "654321" })) ===
        f.fixtureWords(2)
      );
    }),
  );
  check(
    "Restore requires fresh comparison and retains public records",
    await page.evaluate(
      () =>
        localStorage.getItem("clans-public-wallet-recheck-v1:preview:1") === "1" && localStorage.getItem("clans-public-wallet-check-v2:preview:1") !== null,
    ),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-restored-" + theme + ".png",
    });
  }
  await button("Compare wallet code").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).waitFor();
  check("Restore leads to fresh comparison", true);
  return { passed: checks.length, checks };
};
