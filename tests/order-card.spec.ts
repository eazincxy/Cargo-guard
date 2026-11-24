import { test, expect } from "@playwright/test";

const NAV_IFRAME = 'iframe[src*="cargoguard_nav"]';
const ORDERS_IFRAME = 'iframe[src*="cargoguard_order_views"]';

test("订单卡片：无返回箭头且视觉无回归", async ({ page }) => {
  await page.goto("/");

  // 关闭启动开屏动画（覆盖层会拦截点击）
  const splash = page.locator(".cg-splash-overlay");
  if ((await splash.count()) > 0) {
    await splash.click({ force: true }).catch(() => {});
  }

  // 左侧导航是自定义组件 iframe，点击 Orders 进入订单列表
  const nav = page.frameLocator(NAV_IFRAME);
  await expect(nav.locator('button.nav-item[data-tab="orders"]')).toBeVisible({
    timeout: 30000,
  });
  await nav.locator('button.nav-item[data-tab="orders"]').click();

  // 订单卡片位于自定义组件 iframe 内
  const orders = page.frameLocator(ORDERS_IFRAME);
  const cards = orders.locator(".order-card");
  await expect(cards.first()).toBeVisible({ timeout: 30000 });
  await expect(cards.first()).toContainText(/ORD-/);

  // 【关键断言】页面上不存在左上角返回箭头（< 按钮）
  const backArrow = page.locator(
    'button.back, button[aria-label="Back"], button[aria-label="返回"], .back-arrow'
  );
  await expect(backArrow).toHaveCount(0);

  // 视觉回归：与基准图对比，允许少量像素偏差
  await expect(cards.first()).toHaveScreenshot("order-card.png", {
    maxDiffPixelRatio: 0.02,
  });
});
