async (page) => {
  const s = __LOCAL_SESSION__,
    checks = [];
  const check = (n, v) => {
    if (!v) throw new Error(n);
    checks.push(n);
  };
  const c = await page
    .context()
    .browser()
    .newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
  await c.addCookies([
    {
      name: s.cookie_name,
      value: s.owner,
      url: "http://localhost:8415",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const p = await c.newPage();
  await p.goto("http://localhost:8415");
  let first = true,
    accepted,
    requests = [];
  const path = "**/api/clans/" + s.clan_id + "/deposits";
  await p.route(path, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    requests.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postData(),
    });
    if (first) {
      first = false;
      const response = await route.fetch();
      accepted = await response.json();
      return route.fulfill({
        status: 502,
        json: { detail: "Connection interrupted after saving your request." },
      });
    }
    return route.continue();
  });
  await p.getByRole("button", { name: "Add money", exact: true }).click();
  await p
    .getByRole("combobox", { name: "Pay in", exact: true })
    .selectOption("SATS");
  await p
    .getByRole("textbox", { name: "Amount in sats", exact: true })
    .fill("101");
  await p
    .getByRole("button", { name: "Create payment request", exact: true })
    .click();
  await p.locator(".sheet-error").waitFor();
  check(
    "Ambiguous server failure locks the original amount",
    !(await p
      .getByRole("textbox", { name: "Amount in sats", exact: true })
      .isEditable()),
  );
  const response = p.waitForResponse(
    (r) =>
      r.url().endsWith("/deposits") &&
      r.request().method() === "POST" &&
      r.status() === 200,
  );
  await p
    .getByRole("button", { name: "Try the same request again", exact: true })
    .click();
  const recovered = await (await response).json();
  check(
    "Retry returns the originally accepted request",
    accepted.request_id === recovered.request_id,
  );
  check(
    "Retry keeps the same amount and idempotency key",
    requests.length === 2 &&
      requests[0].key === requests[1].key &&
      requests[0].body === requests[1].body,
  );
  await c.close();
  return { checks, passed: checks.length, real_funds_moved: false };
};
