async (page) => {
  const context=await page.context().browser().newContext({viewport:{width:390,height:844}});
  const p=await context.newPage();
  const errors=[]; const checks=[];
  p.on('pageerror',error=>errors.push(error.message));
  p.on('console',message=>{if(message.type()==='error') errors.push(message.text());});
  function check(name,value){if(!value) throw new Error(name);checks.push(name);}
  const landingRequests=[];
  p.on('request',request=>{if(request.url().includes('/api/')) landingRequests.push(request.url());});
  const landing=await p.goto('https://clans.afribit.africa/about/');
  check('Public product page is HTML',landing.status()===200 && landing.headers()['content-type'].includes('text/html'));
  await p.getByRole('heading',{level:1,name:/Help a member/}).waitFor();
  check('Clans belongs to Afribit Wallet',await p.getByText('A feature of Afribit Wallet',{exact:true}).isVisible());
  check('Product page makes no account requests',landingRequests.length===0);
  for(const width of [320,390,768,1366]){
    await p.setViewportSize({width,height:844});
    check('Product page width '+width,await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  const destination=p.locator('summary').filter({hasText:'Where does a grant go?'});
  await destination.click();
  check('Live grant destination explanation',await destination.locator('..').getByText(/The member supplies a Lightning payment request/).isVisible());
  await p.setViewportSize({width:390,height:844});
  await p.evaluate(()=>window.scrollTo(0,0));
  await p.screenshot({path:'output/playwright/clans-product-live.png'});
  const response=await p.goto('https://clans.afribit.africa/');
  check('Public HTTPS welcome',response.status()===200);
  await p.getByRole('button',{name:'Create my account',exact:true}).waitFor();
  await p.evaluate(()=>document.fonts.ready);
  const state=await p.evaluate(async()=>{
    const session=await fetch('/api/session',{cache:'no-store'});
    const ready=await (await fetch('/health/ready',{cache:'no-store'})).json();
    const legacy=await fetch('/api/v1/clans');
    return {session:await session.json(),cache:session.headers.get('cache-control'),ready,legacy:legacy.status};
  });
  check('Anonymous session has no account',state.session.user===null);
  check('Public production capabilities enabled',state.session.capabilities.receiving && state.session.capabilities.payouts);
  check('Financial release and migration active',state.ready.release==='1.7.0' && state.ready.schema==='20261104_08');
  check('Private API is never cached',state.cache==='no-store');
  check('Legacy simulation is inaccessible',state.legacy===404);
  const invitationPage=await p.goto('https://clans.afribit.africa/join');
  check('Invitation links open the account welcome screen',invitationPage.status()===200);
  await p.getByRole('button',{name:'Create my account',exact:true}).waitFor();
  const joinSlash=await p.request.get('https://clans.afribit.africa/join/');
  check('Invitation links also accept a trailing slash',joinSlash.status()===200);
  // The intentional404 above can produce a resource console message.
  const unexpected=errors.filter(message=>!message.includes('404'));
  for(const theme of ['dark','light']){
    const toggle=p.getByRole('button',{name:theme==='light'?'Switch to light mode':'Switch to dark mode'});
    if(await toggle.count()) await toggle.click();
    for(const width of [320,390,768,1366]){
      await p.setViewportSize({width,height:900});
      check(theme+' public layout '+width,await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    await p.setViewportSize({width:390,height:844});
    await p.screenshot({path:'output/playwright/clans-public-welcome-'+theme+'.png',fullPage:true});
  }
  check('No public browser runtime or CSP errors',unexpected.length===0);
  await context.close();
  return {checks:checks.length,passed:checks,unexpected_errors:unexpected,production_accounts_created:0,funds_sent:false};
}
