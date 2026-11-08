async (page) => {
  const s = __LOCAL_SESSION__;
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
  await p
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Activity", exact: true })
    .click();
  const group = p
    .locator("details")
    .filter({
      has: p.locator("summary", { hasText: "Recent grant requests" }),
    });
  await group.locator("summary").click();
  await group.locator(".grant-card").first().waitFor();
  const result = {
    recent_grant_details_preserved:
      (await group.locator(".grant-card").count()) > 0,
    real_funds_moved: false,
  };
  await c.close();
  return result;
};
