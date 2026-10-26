import {test,expect} from '@playwright/test';
import {login} from './auth';
test('mobile read-only host blocks native creation while business policy stays available',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.route('**/api/health',route=>route.fulfill({json:{status:'ok',mode:'host',mutations:false}}));
 await login(page);await page.goto('/accounts');
 await expect(page.getByRole('button',{name:'创建账号'})).toBeDisabled();
 await expect(page.getByText('系统只读',{exact:true})).toBeVisible();
 await page.goto('/advanced/system-groups');await expect(page.getByRole('button',{name:'创建普通权限组'})).toBeDisabled();
 await page.goto('/shares');await expect(page.getByRole('button',{name:'创建共享项目'})).toBeDisabled();
 await page.goto('/groups');await expect(page.getByRole('button',{name:'新建任务策略组'})).toBeEnabled();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
