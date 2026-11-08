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
      viewport: { width: 900, height: 900 },
      reducedMotion: "no-preference",
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
  await p.getByRole("button", { name: "Add money", exact: true }).click();
  await p.locator("dialog").waitFor();
  check(
    "Desktop dialog is centered while opening",
    await p.locator("dialog").evaluate((el) => {
      const r = el.getBoundingClientRect();
      return (
        Math.abs(r.x + r.width / 2 - innerWidth / 2) < 2 &&
        r.right <= innerWidth
      );
    }),
  );
  await p.getByRole("button", { name: "Close dialog", exact: true }).click();
  check(
    "Desktop dialog stays centered while closing",
    await p.locator("dialog").evaluate((el) => {
      const r = el.getBoundingClientRect();
      return Math.abs(r.x + r.width / 2 - innerWidth / 2) < 2;
    }),
  );
  await p.locator("dialog").waitFor({ state: "detached" });
  check("Close animation removes the dialog", true);
  await c.close();
  return { checks, passed: checks.length, real_funds_moved: false };
};
