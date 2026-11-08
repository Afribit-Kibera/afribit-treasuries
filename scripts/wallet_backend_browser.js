async (page) => {
  const local = __LOCAL_WALLET_SESSION__,
    checks = [],
    errors = [];
  const protectedWords = [];
  let secretsSent = false;
  page.on("request", (r) => {
    const body = r.postData() || "";
    if (
      protectedWords.some((w) => body.includes(w)) ||
      body.includes('"123456"')
    )
      secretsSent = true;
  });
  page.on("pageerror", (e) => errors.push(e.message));
  const check = (n, v) => {
    if (!v) throw Error(n);
    checks.push(n);
  };
  const button = (n) => page.getByRole("button", { name: n, exact: true });
  const control = async (action, data = {}) => {
    const r = await page.request.post(
      "http://127.0.0.1:8418/__wallet_test/" + action,
      { headers: { "X-Local-Wallet-Check": local.gate }, data },
    );
    if (!r.ok())
      throw Error("Local network control failed: " + action + " " + r.status());
    return r.json();
  };
  const api = async (path) =>
    page.evaluate(async (path) => {
      const m = await import("/src/live-api.ts");
      return m.api(path);
    }, path);
  const close = async () => {
    await button("Close dialog").click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  };
  async function enter(role) {
    await page.context().clearCookies();
    await page.context().addCookies([
      {
        name: local.cookie_name,
        value: local.sessions[role],
        domain: "localhost",
        path: "/",
        sameSite: "Lax",
      },
    ]);
    await page.goto(local.origin + "/?clan=" + local.clan_id);
    await button("Clan").waitFor();
  }
  async function restore(seed) {
    await button("Clan").click();
    await button("I have a new phone").click();
    const words = await page.evaluate(async (seed) => {
      const f = await import("/src/wallet-fixtures.ts");
      return f.fixtureWords(seed).split(" ");
    }, seed);
    protectedWords.push(words.join(" "));
    for (let i = 0; i < 12; i++)
      await page.getByLabel("Word " + (i + 1), { exact: true }).fill(words[i]);
    await button("Check backup words").click();
    await page
      .getByLabel("Choose a signing key PIN", { exact: true })
      .fill("123456");
    await page
      .getByLabel("Enter the PIN again", { exact: true })
      .fill("123456");
    await button("Protect with a PIN").click();
    await button("Compare wallet code").click();
    await page
      .getByLabel("Your signing key PIN", { exact: true })
      .fill("123456");
    await button("Unlock signing key").click();
    await button("All codes match").click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  }
  async function grant() {
    await button("Home").click();
    await page.getByRole("button", { name: /^Vote/ }).click();
    await button("Review request").click();
    await page
      .getByRole("dialog")
      .getByRole("heading", { name: "Grant request", exact: true })
      .waitFor();
  }
  async function refreshReceipt() {
    await button("Check payment status").click();
    await button("Check payment status").waitFor({ state: "visible" });
    await page.waitForTimeout(200);
  }
  const base = "/clans/" + local.clan_id;
  const destination = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx";
  const other =
    "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7";
  await enter("beneficiary");
  await restore(2);
  check("Real encrypted store restores and compares wallet", true);
  await button("Home").click();
  check(
    "Active Bitcoin wallet is usable without Lightning worker",
    await button("Add money").isEnabled(),
  );
  await button("Add money").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(200);
  const contribution = await api(base + "/wallet/address?purpose=contribution");
  const funded = await control("pay", {
    address: contribution.address,
    amount_sats: 10000,
  });
  await refreshReceipt();
  await page
    .getByText("Waiting for the network · 0 of 3 confirmations", {
      exact: true,
    })
    .waitFor();
  check("Real watcher reports pending receipt", true);
  await control("mine", { txid: funded.txid, blocks: 2 });
  await refreshReceipt();
  await page
    .getByText("Waiting for the network · 2 of 3 confirmations", {
      exact: true,
    })
    .waitFor();
  check(
    "Two confirmations are not credited",
    (await page.locator("img.deposit-qr").count()) === 1,
  );
  await control("mine", { txid: funded.txid, blocks: 3 });
  await refreshReceipt();
  await page
    .getByRole("status")
    .filter({ hasText: /^\s*Received\s*$/ })
    .waitFor();
  check(
    "Three confirmations credit the real ledger",
    (await api(base)).balance_sats === 210000,
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Live receipt " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-live-received-" + theme + ".png",
    });
  }
  await close();
  await button("Add money").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(200);
  check(
    "Earlier confirmed receipt does not complete a new request",
    await page
      .getByRole("status")
      .filter({ hasText: "Waiting for the network" })
      .isVisible(),
  );
  const gone = await control("pay", {
    address: contribution.address,
    amount_sats: 5000,
  });
  await refreshReceipt();
  await control("drop", { txid: gone.txid });
  await refreshReceipt();
  await page
    .getByText(
      "No longer seen on the network. Check your wallet before sending again.",
      { exact: true },
    )
    .waitFor();
  check(
    "Dropped receipt is never marked received",
    (await page.locator("img.deposit-qr").count()) === 1,
  );
  await close();
  await button("Add money").click();
  await page
    .getByLabel("Payment for", { exact: true })
    .selectOption("grant_funding");
  await page.getByLabel("Amount (sats)", { exact: true }).fill("50000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  const main = await api(base + "/wallet/address?purpose=grant_funding");
  check(
    "Clan funding uses checked main address",
    main.index === 0 &&
      (
        await page
          .getByRole("link", { name: "Open Bitcoin wallet" })
          .getAttribute("href")
      ).includes(main.address),
  );
  await close();
  await grant();
  await control("stale");
  await page.getByLabel("Bitcoin address", { exact: true }).fill(destination);
  await button("Check receiving amount").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "The Bitcoin network cannot be checked" })
    .waitFor();
  check(
    "Real 503 gives temporary network message and retry",
    await button("Check receiving amount").isEnabled(),
  );
  await control("tick");
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/payout-address")) posts++;
  });
  await button("Check receiving amount").click();
  await button("Use this Bitcoin address").waitFor();
  check(
    "Quote saves nothing",
    posts === 0 &&
      (await api(base + "/wallet/payouts?grant_id=" + local.grant_id))
        .length === 0,
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Live quote " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-live-quote-" + theme + ".png",
    });
  }
  await button("Use this Bitcoin address").click();
  await page
    .getByText(
      "Address added. Your signatories still need to check and sign the payment.",
      { exact: true },
    )
    .waitFor();
  check("Address saved only on explicit confirmation", posts === 1);
  await control("tick");
  const first = (
    await api(base + "/wallet/payouts?grant_id=" + local.grant_id)
  )[0];
  await button("Use another address").click();
  await page.getByLabel("Bitcoin address", { exact: true }).fill(other);
  await button("Check receiving amount").click();
  await button("Use this Bitcoin address").click();
  await page
    .getByText(
      "Address added. Your signatories still need to check and sign the payment.",
      { exact: true },
    )
    .waitFor();
  await control("tick");
  const drafts = await api(base + "/wallet/payouts?grant_id=" + local.grant_id);
  const newest = drafts.find((d) => d.id !== first.id);
  check(
    "Changed address expires and links the old draft",
    drafts.find((d) => d.id === first.id).status === "expired" &&
      drafts.find((d) => d.id === first.id).replaced_by === newest.id,
  );
  await close();
  await control("third-sign", { id: newest.id });
  await enter("signer");
  await restore(3);
  await grant();
  await button("Sign payout").waitFor();
  check(
    "Current draft includes the other signatory signature",
    (await page.getByRole("dialog").innerText()).includes("1 of 2 signatories"),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        "Live signing " + theme + " " + width,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-live-signing-" + theme + ".png",
    });
  }
  await button("Sign payout").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await page
    .getByRole("status")
    .filter({ hasText: /^Waiting for Afribit$/ })
    .waitFor();
  check(
    "Real API verifies the phone signature and preserves the first signature",
    (await api(base + "/wallet/payouts/" + newest.id)).signatures.count === 2,
  );
  await control("oversight", { id: newest.id });
  await button("Check payout status").click();
  await page
    .getByRole("status")
    .filter({ hasText: /^Sending$/ })
    .waitFor();
  check(
    "Broadcasting is shown as Sending",
    (await button("Sign payout").count()) === 0,
  );
  await control("broadcast-mine", { id: newest.id });
  await button("Check payout status").click();
  await page
    .getByRole("status")
    .filter({ hasText: /^Sent$/ })
    .waitFor();
  check("Watcher broadcasts only after both groups sign", true);
  await control("bump", { id: newest.id });
  await button("Check payout status").click();
  await button("View earlier payment").waitFor();
  const higher = (
    await api(
      base +
        "/wallet/payouts?grant_id=" +
        local.grant_id +
        "&status=awaiting_signatures",
    )
  ).find((p) => p.replaces === newest.id);
  check(
    "Higher-fee version starts without carried-over signatures",
    higher.signatures.count === 0 && !higher.oversight_signed,
  );
  check(
    "Higher fee reduces the beneficiary received amount",
    higher.fee_sats > newest.fee_sats &&
      higher.recipients[0].received_sats < newest.recipients[0].received_sats,
  );
  await button("View earlier payment").click();
  await page
    .getByText(
      "Taking longer than usual. A version with a higher fee needs your signature.",
      { exact: true },
    )
    .waitFor();
  check(
    "Sent payment links to its waiting higher-fee version",
    await button("Review higher-fee payment").isVisible(),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (t) => (document.documentElement.dataset.theme = t),
      theme,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .getByText(
        "Taking longer than usual. A version with a higher fee needs your signature.",
        { exact: true },
      )
      .evaluate((el) =>
        el.scrollIntoView({ block: "center", behavior: "instant" }),
      );
    await page.waitForTimeout(320);
    await page.screenshot({
      path: "output/playwright/clan-wallet-live-higher-fee-" + theme + ".png",
    });
  }
  await button("Review higher-fee payment").click();
  await button("Sign payout").waitFor();
  check(
    "Higher-fee draft is reviewed on the phone again",
    await page.getByText("Checked on this phone", { exact: true }).isVisible(),
  );
  await control("third-sign", { id: higher.id });
  await button("Check payout status").click();
  await button("Sign payout").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await page
    .getByRole("status")
    .filter({ hasText: /^Waiting for Afribit$/ })
    .waitFor();
  check(
    "Higher-fee draft needs two new signatory signatures",
    (await api(base + "/wallet/payouts/" + higher.id)).signatures.count === 2,
  );
  await control("oversight", { id: higher.id });
  await control("broadcast-mine", { id: higher.id });
  check(
    "Original version is replaced only after higher-fee broadcast",
    (await api(base + "/wallet/payouts/" + newest.id)).status === "replaced",
  );
  await control("broadcast-mine", { id: higher.id, confirm: true });
  await button("Check payout status").click();
  await page
    .getByRole("status")
    .filter({ hasText: /^Confirmed$/ })
    .waitFor();
  check(
    "Confirmed payout refreshes grant to repayment",
    (await api(base)).grants.find((g) => g.id === local.grant_id).status ===
      "in_recovery",
  );
  await close();
  await enter("beneficiary");
  await restore(2);
  await button("Home").click();
  await button("Repay").click();
  await page.getByRole("button").filter({ hasText: "left to repay" }).click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(200);
  const repayment = await api(
    base + "/wallet/address?purpose=repayment&grant_id=" + local.grant_id,
  );
  const partial = await control("pay", {
    address: repayment.address,
    amount_sats: 10000,
  });
  await refreshReceipt();
  await control("mine", { txid: partial.txid });
  await refreshReceipt();
  await page
    .getByRole("status")
    .filter({ hasText: /^\s*Received\s*$/ })
    .waitFor();
  check(
    "Partial repayment reduces the real outstanding grant",
    (await api(base)).grants.find((g) => g.id === local.grant_id)
      .outstanding_msat === "30000000",
  );
  await close();
  await button("Home").click();
  await button("Repay").click();
  await page.getByRole("button").filter({ hasText: "left to repay" }).click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("30000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(200);
  const finalPayment = await control("pay", {
    address: repayment.address,
    amount_sats: 30000,
  });
  await refreshReceipt();
  await control("mine", { txid: finalPayment.txid });
  await refreshReceipt();
  await page
    .getByRole("status")
    .filter({ hasText: /^\s*Received\s*$/ })
    .waitFor();
  check(
    "Full repayment clears the outstanding grant",
    (await api(base)).grants.find((g) => g.id === local.grant_id)
      .outstanding_msat === "0",
  );
  await close();
  await button("Repay").click();
  await page
    .getByRole("heading", { name: "Nothing to repay", exact: true })
    .waitFor();
  check("Paid-off grant is no longer offered for repayment", true);
  await close();
  check("No browser runtime errors", errors.length === 0);
  check(
    "Real key restore and signing send no backup words or PIN",
    !secretsSent,
  );
  return {
    passed: checks.length,
    checks,
    network: "local API and watcher; simulated Bitcoin network",
    realFunds: false,
  };
};
