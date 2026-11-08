async (page) => {
  const context=await page.context().browser().newContext({viewport:{width:390,height:844}});
  const p=await context.newPage(); const errors=[]; const checks=[];
  p.on('pageerror',e=>errors.push(e.message));
  function check(name,pass){if(!pass) throw new Error(name);checks.push(name);}
  const cdp=await context.newCDPSession(p);
  await cdp.send('WebAuthn.enable');
  const {authenticatorId}=await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
  await cdp.send('WebAuthn.addCredential',{authenticatorId,credential:__CREDENTIAL__});
  await p.goto('http://localhost:8411/');
  await p.getByRole('button',{name:'Sign in with a passkey',exact:true}).click();
  await p.getByRole('heading',{name:'Clans internal release verification',exact:true}).waitFor();
  check('Actual recovered capital displayed',await p.locator('.balance-number').innerText()==='999.75 sats');
  check('No outstanding recovery principal',(await p.locator('.recovery-strip').allTextContents()).some(value=>value.includes('In recovery') && value.includes('0 sats')));
  await p.getByRole('button',{name:'Review request',exact:true}).click();
  await p.getByText('This grant has been fully recovered. Thank you for keeping the circle moving.',{exact:true}).waitFor();
  check('Grant marked fully recovered in UI',true);
  check('Actual fee retained after recovery',await p.getByText('Confirmed network fee: 0.25 sats',{exact:true}).count()===1);
  await p.screenshot({path:'output/playwright/clans-live-grant-recovered.png',fullPage:true,animations:'disabled'});
  await p.getByRole('button',{name:'Close dialog',exact:true}).click();
  await p.locator('.recent-deposits summary').click();
  await p.locator('.recent-deposits button').filter({has:p.getByText('100 sats',{exact:true})}).click();
  await p.getByText('Deposit confirmed.',{exact:true}).waitFor();
  check('Settled repayment reopens after refresh',true);
  check('Settled invoice no longer offers a payment link',await p.getByRole('link',{name:'Open Lightning wallet',exact:true}).count()===0);
  await p.screenshot({path:'output/playwright/clans-live-recovery-confirmed.png',fullPage:true,animations:'disabled'});
  check('No recovery UI errors',errors.length===0);
  const {credentials}=await cdp.send('WebAuthn.getCredentials',{authenticatorId});
  await context.close();
  return {checks:checks.length,passed:checks,runtime_errors:errors,counter:credentials[0].signCount};
}
