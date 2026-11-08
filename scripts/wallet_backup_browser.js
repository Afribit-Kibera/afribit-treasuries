async (page) => {
  const checks = [],
    errors = [];
  const check = (name, value) => {
    if (!value) throw Error(name);
    checks.push(name);
  };
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://localhost:5182/__wallet_preview");
  await page.evaluate(() => {
    localStorage.removeItem("clans-public-wallet-backup-v1:preview");
    localStorage.removeItem("clans-public-wallet-check-v2:preview:1");
  });
  await page
    .getByRole("button", { name: "Use test signing key", exact: true })
    .click();
  await page.getByRole("button", { name: "Compare wallet code", exact: true }).waitFor();
  await page
    .getByLabel("Wallet status", { exact: true })
    .selectOption("active");
  check(
    "Unchecked phone cannot export",
    (await page
      .getByRole("button", { name: "Save wallet backup", exact: true })
      .count()) === 0,
  );
  await page
    .getByRole("button", {
      name: "Check wallet code on this phone",
      exact: true,
    })
    .click();
  await page.getByLabel("Your signing key PIN", { exact: true }).fill("123456");
  await page
    .getByRole("button", { name: "Unlock signing key", exact: true })
    .click();
  await page.getByLabel("Phone wallet code").waitFor();
  await page
    .getByRole("button", { name: "All codes match", exact: true })
    .click();
  const save = page.getByRole("button", {
    name: "Save wallet backup",
    exact: true,
  });
  await save.waitFor();
  check("Compared active wallet offers backup", await save.isVisible());
  check(
    "Card reminds signatory that words alone are insufficient",
    await page
      .getByText("Save your wallet backup.", { exact: false })
      .isVisible(),
  );
  await save.click();
  const dialog = page.getByRole("dialog", {
    name: "Save wallet backup",
    exact: true,
  });
  await dialog.waitFor();
  check(
    "Backup has no unlock or word fields",
    (await dialog.locator("input").count()) === 0,
  );
  check(
    "Save acknowledgement requires downloading first",
    (await dialog
      .getByRole("button", { name: "I've saved the file", exact: true })
      .count()) === 0,
  );

  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (v) => (document.documentElement.dataset.theme = v),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        `Backup ${theme} fits ${width}`,
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth <= innerWidth &&
            [
              ...document.querySelectorAll(
                "dialog[open], dialog[open] .sheet-inner, dialog[open] .sheet-body",
              ),
            ].every((el) => el.scrollWidth <= el.clientWidth + 1),
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    await page.screenshot({
      path: `output/playwright/clan-wallet-backup-${theme}.png`,
    });
  }
  const requests = [];
  const capture = (r) => {
    if (r.url().includes("/api/")) requests.push(r.url());
  };
  page.on("request", capture);
  await page.evaluate(() => {
    window.__originalBackupURL = URL.createObjectURL;
    URL.createObjectURL = () => {
      throw Error("Download could not start. Try again.");
    };
  });
  await dialog
    .getByRole("button", { name: "Download backup file", exact: true })
    .click();
  check(
    "Download failure shows retry and cannot clear reminder",
    (await dialog.getByRole("alert").innerText()) ===
      "Download could not start. Try again." &&
      (await dialog
        .getByRole("button", { name: "I've saved the file", exact: true })
        .count()) === 0,
  );
  await page.evaluate(() => {
    URL.createObjectURL = (blob) => {
      window.__publicBackupText = blob.text();
      return window.__originalBackupURL(blob);
    };
  });
  const downloadPromise = page.waitForEvent("download");
  await dialog
    .getByRole("button", { name: "Download backup file", exact: true })
    .click();
  const download = await downloadPromise;
  await download.saveAs(".local/wallet-f9-backup.json");
  check(
    "Filename uses the clan name",
    download.suggestedFilename() === "Soweto Traders-wallet-backup.json",
  );
  const backup = JSON.parse(
    await page.evaluate(() => window.__publicBackupText),
  );
  check(
    "Export has exactly the specified public fields",
    Object.keys(backup).sort().join() ===
      "clan_id,descriptors,format,generation,network,oversight,recovery_blocks,recovery_threshold,signers,threshold,wallet_code",
  );
  check(
    "Export identifies the checked wallet",
    backup.format === "afribit-clan-wallet-backup/1" &&
      backup.clan_id === "preview" &&
      backup.generation === 1 &&
      backup.threshold === 2 &&
      backup.wallet_code.length === 8,
  );
  check(
    "Both wallet rules have checksums",
    Object.keys(backup.descriptors).sort().join() === "external,internal" &&
      Object.values(backup.descriptors).every((d) => /#[a-z0-9]{8}$/.test(d)),
  );
  check(
    "Export contains public keys only",
    [...backup.oversight, ...backup.signers].every(
      (k) => k.includes("]tpub") && !k.includes("tprv"),
    ),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (v) => (document.documentElement.dataset.theme = v),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        `Downloaded backup ${theme} fits ${width}`,
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth <= innerWidth &&
            [
              ...document.querySelectorAll(
                "dialog[open], dialog[open] .sheet-body",
              ),
            ].every((el) => el.scrollWidth <= el.clientWidth + 1),
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    await page.screenshot({
      path: `output/playwright/clan-wallet-backup-downloaded-${theme}.png`,
    });
  }
  await dialog
    .getByRole("button", { name: "Close dialog", exact: true })
    .click();
  await dialog.waitFor({ state: "hidden" });
  check(
    "Download alone does not claim the file was saved",
    await page
      .getByText("Save your wallet backup.", { exact: false })
      .isVisible(),
  );
  await save.click();
  check(
    "Reopening requires a new download before acknowledgement",
    (await dialog
      .getByRole("button", { name: "I've saved the file", exact: true })
      .count()) === 0,
  );
  const again = page.waitForEvent("download");
  await dialog
    .getByRole("button", { name: "Download backup file", exact: true })
    .click();
  await (await again).saveAs(".local/wallet-f9-backup.json");
  await page.evaluate(() => {
    window.__originalBackupSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("clans-public-wallet-backup-v1:"))
        throw Error("Storage blocked");
      return window.__originalBackupSetItem.call(this, key, value);
    };
  });
  await dialog
    .getByRole("button", { name: "I've saved the file", exact: true })
    .click();
  check(
    "Blocked device storage preserves the reminder and explains retry",
    (await dialog.getByRole("alert").innerText()).includes("cannot remember"),
  );
  await page.evaluate(
    () => (Storage.prototype.setItem = window.__originalBackupSetItem),
  );
  await dialog
    .getByRole("button", { name: "I've saved the file", exact: true })
    .click();
  await dialog.waitFor({ state: "hidden" });
  check(
    "Acknowledgement clears the reminder",
    await page
      .getByText("Wallet backup saved on this phone.", { exact: false })
      .isVisible(),
  );
  check(
    "Export and acknowledgement send no API requests",
    requests.length === 0,
  );
  page.off("request", capture);
  await page
    .getByRole("button", { name: "Refresh wallet", exact: true })
    .click();
  await save.waitFor();
  check(
    "Saved reminder survives a wallet refresh",
    await page
      .getByText("Wallet backup saved on this phone.", { exact: false })
      .isVisible(),
  );
  for (const theme of ["dark", "light"]) {
    await page.evaluate(
      (v) => (document.documentElement.dataset.theme = v),
      theme,
    );
    for (const width of [320, 390, 430, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      check(
        `Saved backup card ${theme} fits ${width}`,
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .getByRole("region", { name: "Clan wallet", exact: true })
      .evaluate((el) =>
        el.scrollIntoView({ block: "start", behavior: "instant" }),
      );
    await page.waitForTimeout(250);
    await page.screenshot({
      path: `output/playwright/clan-wallet-backup-saved-${theme}.png`,
    });
  }
  const cases = await page.evaluate(async () => {
    const { walletFixture } = await import("/src/wallet-fixtures.ts");
    const { buildWalletBackup, walletBackupFilename, walletBackupSaved } =
      await import("/src/wallet-backup.ts");
    const { saveWalletCheck } = await import("/src/wallet-trust.ts");
    const { walletCode } = await import("/src/vault/policy.ts");
    const { toClanPolicy } = await import("/src/wallet-api.ts");
    const base = walletFixture("active"),
      result = {};
    const rejected = (view) => {
      try {
        buildWalletBackup("preview", view);
        return false;
      } catch {
        return true;
      }
    };
    const spoofed = structuredClone(base);
    spoofed.wallet_code = "xxxxxxxx";
    spoofed.threshold = 99;
    spoofed.oversight_keys = [];
    result["Export ignores server code and summary values"] =
      JSON.stringify(buildWalletBackup("preview", spoofed)) ===
      JSON.stringify(buildWalletBackup("preview", base));
    const alternate = structuredClone(base);
    alternate.policy.signers.reverse();
    result["Changed server policy cannot be exported"] = rejected(alternate);
    result["Uncompared generation cannot be exported"] = rejected({
      ...base,
      generation: 2,
    });
    result["Inactive and disabled wallets cannot export"] =
      rejected({ ...base, enabled: false }) &&
      rejected({ ...base, status: "retired" }) &&
      rejected({ ...base, status: "confirming" });
    result["Ordinary members cannot export"] = rejected({
      ...base,
      me: { ...base.me, is_signer: false },
    });
    const newer = { ...base, generation: 2 };
    saveWalletCheck(
      "preview",
      newer,
      newer.me.key,
      walletCode(toClanPolicy(newer.policy)),
    );
    result["New generation needs a new backup"] = !walletBackupSaved(
      "preview",
      JSON.stringify(buildWalletBackup("preview", newer), null, 2) + "\n",
    );
    const changed = structuredClone(newer);
    changed.policy.signers.reverse();
    saveWalletCheck(
      "preview",
      changed,
      changed.me.key,
      walletCode(toClanPolicy(changed.policy)),
    );
    const rebuilt = buildWalletBackup("preview", changed);
    result["Export preserves compared key order"] =
      JSON.stringify(rebuilt.signers) ===
      JSON.stringify(changed.policy.signers);
    result["Filename removes path characters"] =
      !/[<>:"/\\|?*\u0000-\u001f]/.test(
        walletBackupFilename("../Test\\Clan:Name"),
      ) && walletBackupFilename("...") === "Clan-wallet-backup.json";
    localStorage.setItem("clans-public-wallet-check-v2:preview:1", "not json");
    result["Unreadable checked record cannot export"] = rejected(base);
    return result;
  });
  for (const [name, value] of Object.entries(cases)) check(name, value);
  await page
    .getByRole("button", { name: "Refresh wallet", exact: true })
    .click();
  await page
    .getByText("Compare the wallet code on this phone, then save", {
      exact: false,
    })
    .waitFor();
  check(
    "Lost comparison removes the export button",
    (await save.count()) === 0,
  );
  check("No browser runtime errors", errors.length === 0);
  return {
    passed: checks.length,
    checks,
    fixture: ".local/wallet-f9-backup.json",
  };
};
