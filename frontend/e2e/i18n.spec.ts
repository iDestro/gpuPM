import {test,expect,type Page} from '@playwright/test';
import {login} from './auth';
async function language(page:Page,label:'中文'|'English') {
  await page.locator('.language-select').click();
  await page.getByText(label,{exact:true}).last().click();
}
test('all screens switch to English, remember the choice, and expose Chinese professional terms',async({page})=>{
  const errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await login(page);
  await language(page,'English');
  await expect(page.getByRole('heading',{name:'Server overview',exact:true})).toBeVisible();
  const screens=[['/tasks','GPU tasks'],['/groups','Business priority groups'],['/users','User business policies'],['/accounts','Linux local accounts'],['/system-groups','Linux system groups'],['/storage','Storage and capacity'],['/shares','Team shared directories'],['/login-events','SSH login events'],['/settings','Policies and initialization settings'],['/audit','Operation audit']];
  for(const [path,title] of screens) {
    await page.goto(path);
    await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
    expect(await page.locator('.page-head').innerText()).not.toMatch(/\p{Script=Han}/u);
  }
  await page.reload();
  await expect(page.getByRole('heading',{name:'Operation audit',exact:true})).toBeVisible();
  await expect(page).toHaveTitle('gpuPM · Server management');
  expect(await page.locator('html').getAttribute('lang')).toBe('en');
  await page.goto('/settings');
  await expect(page.getByText('GPU polling interval',{exact:true})).toBeVisible();
  await expect(page.getByText('5 sec',{exact:true})).toBeVisible();
  await language(page,'中文');
  const term=page.getByText('终止等待时间',{exact:true});
  await term.hover();
  await expect(page.getByRole('tooltip')).toHaveText('SIGTERM grace period');
  await term.focus();
  await expect(page.getByRole('tooltip')).toHaveText('SIGTERM grace period');
  await page.mouse.move(0,0);
  await language(page,'English');
  await page.setViewportSize({width:375,height:812});
  await page.getByRole('button',{name:'Open navigation'}).click();
  const drawer=page.getByRole('dialog');
  await drawer.getByRole('menuitem',{name:'GPU tasks'}).click();
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole('heading',{name:'GPU tasks',exact:true})).toBeVisible();
  await expect(page.getByRole('combobox',{name:'语言 / Language'})).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({path:'test-results/i18n-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('English login preserves entered credentials through a language switch',async({page})=>{
  await page.goto('/');
  await page.getByLabel('管理员账号').fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('Strong-admin-pass-42');
  await language(page,'English');
  await expect(page.getByLabel('Administrator account')).toHaveValue('admin');
  await expect(page.getByLabel('Password',{exact:true})).toHaveValue('Strong-admin-pass-42');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Server overview',exact:true})).toBeVisible();
});

test('locale synchronization keeps settings draft and English discard dialog never saves implicitly',async({page})=>{
  await login(page);
  await page.goto('/settings');
  await page.getByRole('button',{name:'编辑策略',exact:true}).click();
  await page.getByRole('button',{name:'4小时',exact:true}).click();
  let patches=0;
  page.on('request',r=>{if(r.method()==='PATCH')patches++;});
  await page.evaluate(()=>{
    localStorage.setItem('gpupm.locale','en-US');
    window.dispatchEvent(new StorageEvent('storage',{key:'gpupm.locale',newValue:'en-US'}));
  });
  await expect(page.getByRole('spinbutton',{name:'Hours',exact:true})).toHaveValue('4');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await expect(page.getByRole('button',{name:'Continue editing',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Continue editing',exact:true}).click();
  await expect(page.getByRole('spinbutton',{name:'Hours',exact:true})).toHaveValue('4');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Discard changes',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(patches).toBe(0);
});
