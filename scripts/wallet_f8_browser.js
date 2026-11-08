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
  await page.evaluate(() => {
    const original = window.fetch;
    window.__walletCase = "normal";
    window.__listCalls = 0;
    window.__quotes = 0;
    window.__saves = 0;
    window.__receiptCalls = 0;
    window.fetch = async (i, o) => {
      const path = new URL(String(i), location.origin);
      const mode = window.__walletCase;
      if (path.pathname.endsWith("/payout-quote")) {
        window.__quotes++;
        if (mode === "network")
          return Response.json(
            { detail: "Bitcoin network information is unavailable." },
            { status: 503 },
          );
      }
      if (path.pathname.endsWith("/payout-address")) {
        window.__saves++;
        if (mode === "funds")
          return Response.json(
            { detail: "The clan needs enough confirmed money for this grant." },
            { status: 409 },
          );
        if (mode === "sent")
          return Response.json(
            { detail: "This grant has already been sent." },
            { status: 409 },
          );
      }
      if (path.pathname.endsWith("/signature") && mode === "signature-refused")
        return Response.json(
          { detail: "A signature doesn't match this payment. Sign it again." },
          { status: 409 },
        );
      const response = await original(i, o);
      if (path.pathname.endsWith("/wallet/payouts")) {
        window.__listCalls++;
        window.__grantFilter = path.searchParams.get("grant_id");
        const rows = await response.json();
        if (mode === "wrong-clan")
          return Response.json(
            rows.map((r) => ({ ...r, clan_id: "another-clan" })),
          );
        if (["linked", "cycle"].includes(mode))
          return Response.json(
            rows.map((r) => ({
              ...r,
              status: "expired",
              replaced_by: mode === "cycle" ? r.id : "fixture-new",
            })),
          );
        return Response.json(rows);
      }
      if (path.pathname.endsWith("/wallet/payouts/fixture-new")) {
        const f = await import("/src/wallet-payout-fixture.ts");
        return Response.json({
          ...f.fixturePayout,
          id: "fixture-new",
          replaces: "fixture-payout",
        });
      }
      if (
        path.pathname.endsWith("/wallet/payouts/fixture-payout") &&
        mode === "cycle"
      ) {
        const f = await import("/src/wallet-payout-fixture.ts");
        return Response.json({
          ...f.fixturePayout,
          status: "expired",
          replaced_by: "fixture-payout",
        });
      }
      if (
        path.pathname.endsWith("/wallet/payouts/fixture-payout") &&
        mode === "retired"
      ) {
        const f = await import("/src/wallet-payout-fixture.ts");
        return Response.json({
          ...f.fixturePayout,
          status: "expired",
          replaced_by: "fixture-new",
        });
      }
      if (path.pathname.endsWith("/wallet/receipts")) {
        window.__receiptCalls++;
        if (mode === "receipt-offline")
          return Response.json(
            { detail: "Connection lost. Check again." },
            { status: 503 },
          );
        const address = path.searchParams.get("address");
        const row = {
          id: "2".repeat(64) + ":0",
          txid: "2".repeat(64),
          vout: 0,
          address,
          purpose: "contribution",
          grant_id: null,
          amount_sats: 10000,
          confirmations: 3,
          status: "confirmed",
        };
        if (mode === "wrong-address")
          return Response.json([{ ...row, address: "tb1-other-address" }]);
        if (mode === "wrong-purpose")
          return Response.json([
            { ...row, purpose: "repayment", grant_id: "another-grant" },
          ]);
        if (mode === "early-confirmed")
          return Response.json([{ ...row, confirmations: 2 }]);
        if (mode === "duplicate") return Response.json([row, row]);
        if (mode === "conflict")
          return Response.json([row, { ...row, amount_sats: 20000 }]);
        return Response.json([]);
      }
      return response;
    };
  });
  const mode = async (v) => page.evaluate((v) => (window.__walletCase = v), v);
  await button("Review test payout").click();
  await button("Sign payout").waitFor();
  check(
    "One grant-filtered list replaces six status requests",
    await page.evaluate(
      () =>
        window.__listCalls === 1 && window.__grantFilter === "fixture-grant",
    ),
  );
  await mode("signature-refused");
  await button("Sign payout").click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await button("Unlock signing key").click();
  await page
    .getByRole("alert")
    .filter({
      hasText: "A signature doesn't match this payment. Sign it again.",
    })
    .waitFor();
  check(
    "Signature 409 is visible and not retried",
    (await button("Sign payout").count()) === 0 &&
      (await button("Refresh payout").isVisible()),
  );
  check(
    "Signature refusal leaves draft unsigned",
    await page.evaluate(
      async () =>
        !(
          await (
            await fetch("/api/clans/preview/wallet/payouts/fixture-payout")
          ).json()
        ).signatures.signed_by_me,
    ),
  );
  await close();
  await mode("wrong-clan");
  await button("Review test payout").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "does not match your clan and grant" })
    .waitFor();
  check(
    "Another clan payout is never signable",
    (await button("Sign payout").count()) === 0,
  );
  await close();
  await mode("linked");
  await button("Review test payout").click();
  await button("Sign payout").waitFor();
  check(
    "Replacement chain opens the checked current draft",
    await page.getByText("Checked on this phone", { exact: true }).isVisible(),
  );
  await close();
  await mode("cycle");
  await button("Review test payout").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "versions could not be checked" })
    .waitFor();
  check(
    "Cyclic replacement links stop safely",
    (await button("Sign payout").count()) === 0,
  );
  await close();
  await mode("network");
  await button("Add test receiving address").click();
  await page
    .getByLabel("Bitcoin address", { exact: true })
    .fill("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx");
  await button("Check receiving amount").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "Bitcoin network cannot be checked" })
    .waitFor();
  check(
    "503 never presents an address confirmation",
    (await button("Use this Bitcoin address").count()) === 0 &&
      (await button("Check receiving amount").isEnabled()),
  );
  await mode("funds");
  await button("Check receiving amount").click();
  await button("Use this Bitcoin address").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "Wait for the clan’s deposits to confirm" })
    .waitFor();
  check(
    "Insufficient confirmed funds keeps the quote retryable",
    await button("Use this Bitcoin address").isEnabled(),
  );
  await mode("sent");
  await button("Use this Bitcoin address").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "This grant has already been sent." })
    .waitFor();
  check(
    "Already-sent rejection does not claim the address was saved",
    (await page
      .getByText(
        "Address added. Your signatories still need to check and sign the payment.",
        { exact: true },
      )
      .count()) === 0,
  );
  await close();
  await mode("normal");
  await button("Test contribution").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("15000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(100);
  for (const value of [
    "wrong-address",
    "wrong-purpose",
    "early-confirmed",
    "conflict",
  ]) {
    await mode(value);
    await button("Check payment status").click();
    await page.getByRole("alert").waitFor();
    check(
      value + " cannot credit a payment",
      (await page.locator("img.deposit-qr").count()) === 1 &&
        (await page
          .getByRole("status")
          .filter({ hasText: "Waiting for the network" })
          .isVisible()),
    );
  }
  await mode("duplicate");
  await button("Check payment status").click();
  await page.getByText(/received so far/i).waitFor();
  check(
    "Repeated txid:vout counts only once",
    (await page
      .getByLabel("Payments to this address")
      .locator(".wallet-money")
      .count()) === 1 && (await page.locator("img.deposit-qr").count()) === 1,
  );
  await mode("receipt-offline");
  await button("Check payment status").click();
  await page
    .getByRole("alert")
    .filter({ hasText: "Connection lost" })
    .waitFor();
  check(
    "Receipt outage has a manual retry",
    await button("Check payment status").isEnabled(),
  );
  await close();
  await mode("normal");
  await page.clock.install();
  await button("Review test payout").click();
  await button("Sign payout").waitFor();
  await mode("retired");
  await page.clock.fastForward(30000);
  await button("Open the latest payment").waitFor();
  check(
    "Expired draft explains the changed receiving address",
    (await page.getByText(/The receiving address changed/).isVisible()) &&
      (await button("Sign payout").count()) === 0,
  );
  await button("Open the latest payment").click();
  await button("Sign payout").waitFor();
  check(
    "Latest-payment link requires review again",
    await page.getByText("Checked on this phone", { exact: true }).isVisible(),
  );
  await close();
  await mode("normal");
  await button("Test contribution").click();
  await page.getByLabel("Amount (sats)", { exact: true }).fill("10000");
  await button("Get payment address").click();
  await page.locator("img.deposit-qr").waitFor();
  await page.waitForTimeout(100);
  const count = await page.evaluate(() => window.__receiptCalls);
  await page.clock.fastForward(29000);
  check(
    "Receipt poll waits thirty seconds",
    (await page.evaluate(() => window.__receiptCalls)) === count,
  );
  await page.clock.fastForward(1000);
  await page.waitForTimeout(100);
  check(
    "Waiting receipt polls after thirty seconds",
    (await page.evaluate(() => window.__receiptCalls)) > count,
  );
  return { passed: checks.length, checks };
};
