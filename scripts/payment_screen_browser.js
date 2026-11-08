async (page) => {
  // Run only against the loopback fixture server: no real provider or payments.
  const context = await page.context().browser().newContext({viewport: {width: 390, height: 844}, permissions: ['clipboard-write']});
  const p = await context.newPage();
  await p.addInitScript(() => {
    window.__walletTest = {enabled: false, invoice: ''};
    window.webln = {
      enable: async () => {window.__walletTest.enabled = true;},
      sendPayment: async invoice => {window.__walletTest.invoice = invoice; return {};},
    };
  });
  const checks = [];
  const check = (name, value) => {if (!value) throw new Error(name); checks.push(name);};
  const cdp = await context.newCDPSession(p);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await p.goto('http://localhost:8412');
  await p.getByRole('button', {name: 'Create my account', exact: true}).click();
  await p.getByRole('textbox', {name: 'Your name', exact: true}).fill('Payment Screen Review');
  await p.getByRole('textbox', {name: 'Choose a username'}).fill('payment_' + Date.now());
  await p.getByRole('textbox', {name: 'Phone number', exact: true}).fill('+254700000001');
  await p.locator('input[name="terms"]').check();
  await p.getByRole('button', {name: 'Continue to security'}).click();
  await p.getByRole('button', {name: 'Create my passkey', exact: true}).click();
  await p.getByRole('checkbox', {name: 'I saved my username and 12 words.'}).check();
  await p.getByRole('button', {name: 'Continue to my account'}).click();
  await p.getByRole('button', {name: 'Create a clan', exact: true}).click();
  await p.getByRole('textbox', {name: 'Clan name', exact: true}).fill('Payment Screen Clan');
  await p.getByRole('button', {name: 'Choose who approves'}).click();
  await p.getByRole('checkbox', {name: 'I also choose to be one of the signatories.'}).check();
  await p.getByRole('checkbox', {name: 'I acknowledge these custody terms and will share them with members.'}).check();
  await p.getByRole('button', {name: 'Create Payment Screen Clan', exact: true}).click();
  await p.getByRole('button', {name: 'Add money', exact: true}).click();
  await p.getByRole('spinbutton', {name: 'Amount in sats', exact: true}).fill('1000');
  await p.getByRole('button', {name: 'Create payment request', exact: true}).click();
  await p.locator('.deposit-qr').waitFor();
  check('Payment request has a QR code', await p.locator('.deposit-qr').isVisible());
  const wallets = p.getByRole('combobox', {name: 'Pay with', exact: true});
  await wallets.selectOption('blink');
  check('Blink paste instructions are shown', (await p.locator('.wallet-help').innerText()).includes('Blink'));
  await wallets.selectOption('fedi');
  check('Fedi paste instructions are shown', (await p.locator('.wallet-help').innerText()).includes('Fedi'));
  check('Standard wallet link is used', (await p.getByRole('link', {name: 'Open a wallet', exact: true}).getAttribute('href')).startsWith('lightning:lnbc'));
  await p.getByRole('button', {name: 'Pay in this wallet', exact: true}).click();
  check('WebLN requires a deliberate action and receives the invoice', await p.evaluate(() => window.__walletTest.enabled && window.__walletTest.invoice.startsWith('lnbc')));
  check('Client wallet response cannot credit clan money', await p.evaluate(async () => {
    const session = await (await fetch('/api/session')).json();
    const clan = await (await fetch('/api/clans/' + session.clans[0].id)).json();
    return clan.balance_msat === '0';
  }));
  await p.getByRole('button', {name: 'Copy payment request'}).click();
  await p.locator('.copy-toast').waitFor();
  check('Copy confirmation is visible inside full-screen payment task', await p.locator('.copy-toast').isVisible());
  for (const width of [320, 390, 768]) {
    await p.setViewportSize({width, height: 844});
    check('Payment task does not overflow at ' + width, await p.locator('.sheet-body').evaluate(el => el.scrollWidth <= el.clientWidth));
  }
  await p.setViewportSize({width: 390, height: 844});
  await p.locator('.sheet-body').evaluate(el => el.scrollTop = 0);
  await p.screenshot({path: 'output/playwright/clans-payment-screen-dark.png'});
  await p.getByRole('button', {name: 'Close dialog'}).click();
  await p.getByRole('button', {name: 'Switch to light mode'}).click();
  await p.getByRole('button', {name: 'Add money', exact: true}).click();
  check('Add-money form is full screen', await p.locator('dialog').evaluate(el => el.clientHeight === innerHeight));
  await p.screenshot({path: 'output/playwright/clans-add-money-light.png'});
  await context.close();
  return {checks, environment: 'Loopback-only API with test transport and real WebAuthn; no production accounts or provider calls', mainnet_funds_moved: false};
}
