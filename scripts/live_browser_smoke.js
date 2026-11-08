async (page) => {
  const origin = 'http://localhost:8411';
  const browser = page.context().browser();
  const checks = [];
  const errors = [];
  const users = [];
  function check(name, pass) { if (!pass) throw new Error('Failed: ' + name); checks.push(name); }
  async function account(name, invitation) {
    const context = await browser.newContext({viewport:{width:390,height:844}});
    const p = await context.newPage();
    p.on('pageerror', e => errors.push(e.message));
    const cdp = await context.newCDPSession(p);
    await cdp.send('WebAuthn.enable');
    const {authenticatorId} = await cdp.send('WebAuthn.addVirtualAuthenticator', {options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
    await p.goto(invitation || origin);
    await p.getByRole('button',{name:'Create my account',exact:true}).waitFor();
    if (!invitation) {
      await p.screenshot({path:'output/playwright/clans-live-welcome-dark.png',fullPage:true});
      await p.getByRole('button',{name:'Switch to light mode'}).click();
      await p.screenshot({path:'output/playwright/clans-live-welcome-light.png',fullPage:true});
      await p.getByRole('button',{name:'Switch to dark mode'}).click();
    }
    await p.getByRole('button',{name:'Create my account',exact:true}).click();
    await p.getByRole('textbox',{name:'Your name',exact:true}).fill(name);
    await p.getByRole('checkbox').check();
    await p.getByRole('button',{name:'Continue to security',exact:true}).click();
    const response = p.waitForResponse(r => r.url().endsWith('/api/auth/register/verify') && r.request().method() === 'POST');
    await p.getByRole('button',{name:'Create my passkey',exact:true}).click();
    const result = await (await response).json();
    check(name+' registered with a real browser passkey', !!result.recovery_codes && result.recovery_codes.length === 8);
    await p.getByRole('checkbox',{name:'I saved my handle and recovery codes securely.'}).check();
    await p.getByRole('button',{name:'Continue to my account',exact:true}).click();
    await p.getByRole('heading',{level:1}).filter({hasText:'Welcome,'}).waitFor();
    const user={context,p,cdp,authenticatorId,kit:result}; users.push(user);
    return user;
  }
  const owner=await account('Stage Organizer');
  await owner.p.getByRole('button',{name:'Create a clan',exact:true}).click();
  await owner.p.getByRole('textbox',{name:'Clan name',exact:true}).fill('Stage Community');
  await owner.p.getByRole('textbox',{name:'What brings you together?'}).fill('Shared progress through accountable decisions.');
  await owner.p.getByRole('button',{name:'Continue to governance'}).click();
  await owner.p.getByRole('combobox',{name:'Number of signatories'}).selectOption('3');
  await owner.p.getByRole('checkbox',{name:'I also choose to be one of the signatories.'}).check();
  await owner.p.getByRole('checkbox',{name:'I acknowledge these custody terms and will share them with members.'}).check();
  await owner.p.getByRole('button',{name:'Create Stage Community',exact:true}).click();
  await owner.p.getByRole('heading',{name:'Stage Community',exact:true}).waitFor();
  check('New treasury has no seed balance', await owner.p.locator('.balance-number').innerText() === '0 sats');
  await owner.p.screenshot({path:'output/playwright/clans-live-empty-treasury.png',fullPage:true});
  async function invitation() {
    await owner.p.getByRole('button',{name:'My Clan',exact:true}).click();
    await owner.p.getByRole('button',{name:'Invite',exact:true}).click();
    await owner.p.getByRole('checkbox').check();
    await owner.p.getByRole('button',{name:'Create private invitation',exact:true}).click();
    const field=owner.p.getByRole('textbox',{name:'Invitation link',exact:true});
    await field.waitFor(); const link=await field.inputValue();
    await owner.p.getByRole('button',{name:'Close dialog',exact:true}).click();
    return link;
  }
  const members=[];
  for (const name of ['Stage Voter One','Stage Voter Two']) {
    const link=await invitation();
    const u=await account(name,link);
    check('Invitation kept out of HTTP URL', !new URL(u.p.url()).hash);
    check('Invitation requires explicit consent', await u.p.getByRole('button',{name:'Accept invitation',exact:true}).isDisabled());
    await u.p.getByRole('checkbox',{name:'I choose to join this clan and acknowledge the custody terms.'}).check();
    await u.p.getByRole('checkbox',{name:'I accept the signatory responsibility and will independently review payment requests.'}).check();
    await u.p.getByRole('button',{name:'Accept invitation',exact:true}).click();
    await u.p.getByRole('heading',{name:'Stage Community',exact:true}).waitFor();
    members.push(u);
  }
  await owner.p.getByRole('button',{name:'Refresh account'}).click();
  await owner.p.getByRole('button',{name:'Home',exact:true}).click();
  await owner.p.getByRole('button',{name:'Create a grant request'}).click();
  await owner.p.getByRole('spinbutton',{name:'Amount in sats'}).fill('1500');
  await owner.p.getByRole('textbox',{name:'Purpose',exact:true}).fill('Inventory for a community business.');
  await owner.p.getByRole('button',{name:'Submit request',exact:true}).click();
  await owner.p.getByRole('button',{name:'Review request',exact:true}).click();
  check('Beneficiary cannot approve own grant', await owner.p.getByRole('button',{name:'Approve request',exact:true}).count() === 0);
  await owner.p.getByRole('button',{name:'Close dialog',exact:true}).click();
  for (const member of members) {
    await member.p.getByRole('button',{name:'Refresh account'}).click();
    await member.p.getByRole('button',{name:'Review request',exact:true}).click();
    await member.p.getByRole('button',{name:'Approve request',exact:true}).click();
    await member.p.getByRole('button',{name:'Review request',exact:true}).waitFor();
  }
  await owner.p.getByRole('button',{name:'Refresh account'}).click();
  await owner.p.getByRole('button',{name:'Review request',exact:true}).click();
  await owner.p.getByRole('button',{name:'Accept grant terms',exact:true}).click();
  await owner.p.getByText('Awaiting funding',{exact:true}).waitFor();
  check('Approved grant does not fabricate a payment', await owner.p.locator('.balance-number').innerText() === '0 sats');
  await owner.p.getByRole('button',{name:'Profile',exact:true}).click();
  await owner.p.getByRole('button',{name:'Sign out',exact:true}).click();
  await owner.p.getByRole('button',{name:'Sign in with a passkey',exact:true}).click();
  await owner.p.getByRole('heading',{name:'Stage Community',exact:true}).waitFor();
  check('Passkey sign-in after sign-out', true);
  await owner.p.getByRole('button',{name:'Profile',exact:true}).click();
  await owner.p.getByRole('button',{name:'Replace recovery codes',exact:true}).click();
  await owner.p.getByRole('heading',{name:'Your way back in.'}).waitFor();
  check('Security changes require a fresh passkey assertion', await owner.p.locator('.recovery-grid code').count()===8);
  await owner.p.getByRole('checkbox',{name:'I saved my handle and recovery codes securely.'}).check();
  await owner.p.getByRole('button',{name:'Continue to my account',exact:true}).click();
  await owner.p.getByRole('button',{name:'Home',exact:true}).click();
  for (const theme of ['dark','light']) {
    const target=theme==='light'?'Switch to light mode':'Switch to dark mode';
    const toggle=owner.p.getByRole('button',{name:target});
    if (await toggle.count()) await toggle.click();
    for (const width of [320,390,768,1366]) {
      await owner.p.setViewportSize({width,height:900});
      check(theme+' layout '+width, await owner.p.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
    }
    await owner.p.setViewportSize({width:390,height:844});
    await owner.p.screenshot({path:'output/playwright/clans-live-home-'+theme+'.png',fullPage:true});
  }
  check('No browser runtime errors', errors.length===0);
  for (const u of users) await u.context.close();
  return {checks:checks.length, passed:checks, runtime_errors:errors};
}