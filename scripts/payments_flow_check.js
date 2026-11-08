async (page) => {
  const s = __LOCAL_SESSION__,
    checks = [],
    errors = [];
  const check = (name, ok) => {
    if (!ok) throw new Error(name);
    checks.push(name);
  };
  const browser = page.context().browser();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    permissions: ["clipboard-read", "clipboard-write"],
  });
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
  await p.goto("http://localhost:8415");
  await p.getByRole("button", { name: "Clan", exact: true }).click();
  check(
    "Club overview has three destinations",
    (await p.locator(".club-menu>button").count()) === 3,
  );
  await p.getByRole("button", { name: "Members 4", exact: true }).click();
  check(
    "Members open on their own screen",
    await p.getByRole("heading", { name: "Members", exact: true }).isVisible(),
  );
  await p.getByRole("button", { name: "My clan", exact: true }).click();
  await p.getByRole("button", { name: "Signatories 3", exact: true }).click();
  check(
    "Signatories filter the roster",
    (await p.locator(".live-member").count()) === 3,
  );
  await p.getByRole("button", { name: "My clan", exact: true }).click();
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-club-dark.png",
  });
  await p
    .getByRole("button", { name: "Switch to light mode", exact: true })
    .click();
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-club-light.png",
  });
  await p.getByRole("button", { name: "Profile", exact: true }).click();
  check(
    "Profile is a menu",
    (await p.locator(".settings-menu>button").count()) === 6,
  );
  check(
    "Security controls stay on their subpage",
    (await p
      .getByRole("button", { name: "Get new recovery words", exact: true })
      .count()) === 0,
  );
  for (const name of [
    "My details",
    "Passkeys & recovery",
    "Country & currency",
    "Payment limits",
    "Install Clans",
    "About your membership",
  ]) {
    await p
      .getByRole("button", { name: new RegExp("^" + name.replace("&", "&")) })
      .click();
    check(
      name + " opens",
      (await p.locator(".profile-screens>h2").innerText()) === name,
    );
    await p
      .getByRole("button", { name: "Profile", exact: true })
      .first()
      .click();
  }
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-profile-menu.png",
  });
  await p.getByRole("button", { name: "Activity", exact: true }).click();
  await p.locator(".month-picker input").waitFor();
  await p.locator(".activity-list").waitFor();
  check(
    "Activity month has ledger rows",
    (await p.locator(".ledger-row").count()) > 0,
  );
  await p.getByRole("button", { name: "Previous month", exact: true }).click();
  await p.getByText("No activity this month.", { exact: true }).waitFor();
  check("Empty month is explicit", true);
  await p.getByRole("button", { name: "Next month", exact: true }).click();
  await p.locator(".ledger-row").first().waitFor();
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-monthly-activity.png",
  });
  await p.getByRole("button", { name: "Home", exact: true }).click();
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
  await p.locator(".deposit-qr").waitFor();
  check(
    "Payment steps show pay",
    (await p.locator(".payment-steps [aria-current=step]").innerText()).replace(
      /\s+/g,
      "",
    ) === "2Pay",
  );
  const requestURL = p.url();
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-deposit-pay.png",
  });
  for (const width of [320, 390, 768]) {
    await p.setViewportSize({ width, height: 844 });
    check(
      "Deposit fits " + width,
      await p
        .locator(".sheet-body")
        .evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    );
  }
  await p.getByRole("button", { name: "Close dialog", exact: true }).click();
  await p.locator("dialog").waitFor({ state: "detached" });
  await p
    .getByRole("button", { name: /^Continue payment/ })
    .first()
    .click();
  await p.locator(".deposit-qr").waitFor();
  check("Unfinished payment resumes from Home", true);
  const deposits = await p.evaluate(async (cid) => {
    const r = await fetch("/api/clans/" + cid + "?include_activity=false");
    return (await r.json()).deposits;
  }, s.clan_id);
  const pending = deposits.find((d) => d.status === "pending");
  await p.goto(
    "http://localhost:8415/?payment=" +
      pending.id +
      "&clan=" +
      s.clan_id +
      "&status=paid",
  );
  await p.locator(".deposit-qr").waitFor();
  check("Checkout return resumes the same invoice", true);
  check(
    "Return URL cannot mark it paid",
    (await p
      .getByRole("heading", { name: "Money received", exact: true })
      .count()) === 0,
  );
  await p.request.post("http://localhost:8415/__fixture/settle");
  await p.evaluate(() => window.dispatchEvent(new Event("focus")));
  await p
    .getByRole("heading", { name: "Money received", exact: true })
    .waitFor();
  check("Verified settlement updates after wallet return", true);
  await p.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-deposit-confirmed.png",
  });
  await p.getByRole("button", { name: "Done", exact: true }).click();
  await p.getByRole("button", { name: "Clan", exact: true }).click();
  await p.getByRole("button", { name: "Invite member", exact: true }).click();
  await p
    .getByRole("button", { name: "Create private invitation", exact: true })
    .click();
  const invite = await p
    .getByRole("textbox", { name: "Invitation link", exact: true })
    .inputValue();
  const newcomer = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const friend = await newcomer.newPage();
  friend.on("pageerror", (e) => errors.push(e.message));
  let downloads = 0;
  friend.on("download", () => downloads++);
  const cdp = await newcomer.newCDPSession(friend);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  const response = await friend.goto(invite);
  check(
    "Invitation delivers HTML",
    response.headers()["content-type"].includes("text/html"),
  );
  await friend
    .getByRole("button", { name: "Create my account", exact: true })
    .click();
  await friend
    .getByRole("textbox", { name: "Your name", exact: true })
    .fill("Invited member");
  await friend
    .getByRole("textbox", { name: "Choose a username", exact: true })
    .fill("invite_" + Date.now());
  await friend
    .getByRole("textbox", { name: "Phone number", exact: true })
    .fill("0700000001");
  await friend.locator("input[name=terms]").check();
  await friend
    .getByRole("button", { name: "Continue to security", exact: true })
    .click();
  await friend
    .getByRole("button", { name: "Create my passkey", exact: true })
    .click();
  await friend
    .getByRole("checkbox", {
      name: "I saved my username and 12 words.",
      exact: true,
    })
    .check();
  check(
    "File download is clearly optional",
    await friend
      .getByRole("button", {
        name: "Download a backup (optional)",
        exact: true,
      })
      .isVisible(),
  );
  await friend
    .getByRole("button", { name: "Continue to invitation", exact: true })
    .click();
  await friend.getByRole("checkbox", { name: /I choose to join/ }).check();
  await friend.getByRole("button", { name: /Accept/ }).click();
  await friend
    .getByRole("button", { name: "Receive grant", exact: true })
    .waitFor();
  check("New member joins without any file download", downloads === 0);
  await friend.screenshot({
    animations: "disabled",
    path: "output/playwright/clans-invited-member.png",
  });
  await newcomer.close();
  await context.close();
  return { checks, errors, passed: checks.length, real_funds_moved: false };
};
