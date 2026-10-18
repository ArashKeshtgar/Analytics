/**
 * The dashboard in a real browser, signed in through a fake ClinicHub (PKCE enforced), calling the real
 * API over a warehouse built from the synthetic source (tests/e2e_stack.py).
 *
 * Numbers are worked out by hand from that data:
 *   revenue (posting month):  Harbourview  Sep 2026 250, Oct 2026 200, Oct 2025 90
 *                             lab          Oct 2026  70, Oct 2025 60       -> group Oct 270 vs 150 (+80.0%)
 *   OHIP, by receivable item: billed 300 (Sep 100, Oct 200), paid 60, outstanding 210,
 *                             refused 30 (10.0%), short-paid 10 (3.3%)
 *   ageing on 2026-10-31:     OHIP current 200, 1-30 10; patients 1-30 50; payables: supplier 31-60 40
 *   HST (last 12 months):     sales 520, collected 13, ITCs 26 -> 13 refundable
 */
import { readFile } from 'node:fs/promises';
import { expect, type Page, test } from '@playwright/test';

const IDP = 'http://localhost:5301';

async function signInAs(page: Page, user: 'group' | 'clinic' | 'nobody', path = '/') {
  const response = await page.request.get(`${IDP}/__user?name=${user}`);
  expect(response.status()).toBe(204);
  await page.goto(path);
}

const errors = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => {
  const seen: string[] = [];
  errors.set(page, seen);
  page.on('console', (m) => {
    if (m.type() === 'error') seen.push(m.text());
  });
  page.on('pageerror', (e) => seen.push(`pageerror: ${e.message}`));
});
test.afterEach(async ({ page }) => {
  expect(errors.get(page), 'errors in the browser console').toEqual([]);
});

// A tile by its exact label ('Paid' must not match 'Short-paid rate').
const tile = (page: Page, label: string) =>
  page.locator('.tile').filter({ has: page.locator('.tile-label', { hasText: new RegExp(`^${label}$`) }) });

test.describe('signing in', () => {
  test('goes through the sign-in service and comes back to the page that was asked for', async ({ page }) => {
    await signInAs(page, 'group', '/ohip');
    await expect(page.getByRole('heading', { name: 'By provider' })).toBeVisible();
    await expect(page).toHaveURL('http://localhost:5601/ohip');
    await expect(page.getByText('Grace Group')).toBeVisible();
    // the tokens are kept for the tab only
    expect(await page.evaluate(() => Object.keys(window.localStorage).filter((k) => k.startsWith('oidc')))).toEqual([]);
    expect(await page.evaluate(() => Object.keys(window.sessionStorage).some((k) => k.startsWith('oidc.user')))).toBe(true);
  });

  test('a user without an Analytics permission is told so', async ({ page }) => {
    await signInAs(page, 'nobody');
    await expect(page.getByRole('heading', { name: 'No access to Analytics' })).toBeVisible();
    await expect(page.locator('.nav')).toHaveCount(0);
  });

  test('signing out ends the session until you sign in again', async ({ page }) => {
    await signInAs(page, 'group');
    await expect(page.locator('.tile-hero')).toBeVisible();
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByRole('heading', { name: 'Signed out' })).toBeVisible();
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.locator('.tile-hero')).toBeVisible();
  });

  test('an expired token sends you through sign-in again without losing the page', async ({ page }) => {
    await page.request.get(`${IDP}/__lifetime?seconds=3`);
    await signInAs(page, 'group', '/receivables');
    await expect(tile(page, 'Receivables outstanding')).toBeVisible();
    await page.request.get(`${IDP}/__lifetime?seconds=300`);
    await page.waitForTimeout(4000);
    await page.getByRole('link', { name: 'HST' }).click();
    await expect(tile(page, 'HST collected')).toBeVisible({ timeout: 15_000 });
  });
});

test.describe('overview', () => {
  test('leads with the month’s revenue against the same month a year earlier', async ({ page }) => {
    await signInAs(page, 'group');
    const hero = page.locator('.tile-hero');
    await expect(hero).toContainText('Revenue, Oct 2026');
    await expect(hero).toContainText('$270');
    await expect(hero).toContainText('+80.0% vs Oct 2025');
    // exactly one hero figure on the view
    await expect(page.locator('.tile-hero')).toHaveCount(1);
  });

  test('the table twin of the line-of-business chart has the numbers', async ({ page }) => {
    await signInAs(page, 'group');
    const card = page.locator('section.card', { hasText: 'Revenue by line of business' });
    await card.getByRole('button', { name: 'Table' }).click();
    const rows = card.locator('tbody tr');
    await expect(rows.nth(0)).toContainText('Clinic');
    await expect(rows.nth(0)).toContainText('$200.00');
    await expect(rows.nth(0)).toContainText('$90.00');
    await expect(rows.nth(1)).toContainText('Lab');
    await expect(rows.nth(1)).toContainText('$70.00');
    await expect(card.locator('tfoot')).toContainText('$270.00');
    await expect(card.locator('tfoot')).toContainText('$150.00');
    await expect(card.locator('tfoot')).toContainText('80.0%');
  });

  test('hovering and focusing a bar shows every series', async ({ page }) => {
    await signInAs(page, 'group');
    const card = page.locator('section.card', { hasText: 'Revenue by line of business' });
    const clinic = card.getByLabel('Clinic: Oct 2026 $200, Oct 2025 $90');
    await clinic.hover();
    await expect(card.getByRole('tooltip')).toContainText('$200');
    await expect(card.getByRole('tooltip')).toContainText('$90');
    await page.mouse.move(0, 0);
    await expect(card.getByRole('tooltip')).toHaveCount(0);
    await clinic.focus();
    await expect(card.getByRole('tooltip')).toContainText('Clinic');
  });

  test('the business filter narrows every number', async ({ page }) => {
    await signInAs(page, 'group');
    await page.getByRole('combobox', { name: 'Business' }).selectOption('LAB');
    const hero = page.locator('.tile-hero');
    await expect(hero).toContainText('$70');
    await expect(hero).toContainText('+16.7% vs Oct 2025');
  });

  test('"last year" is about the last month that has books in it, not an empty December', async ({ page }) => {
    await signInAs(page, 'group');
    await page.getByRole('button', { name: 'Last year' }).click();
    const hero = page.locator('.tile-hero');
    await expect(hero).toContainText('Revenue, Oct 2025');
    await expect(hero).toContainText('$150');
    await expect(page.getByText('No books for Oct 2024')).toBeVisible();
  });

  test('a clinic user sees their own clinic only, and no group page', async ({ page }) => {
    await signInAs(page, 'clinic');
    const hero = page.locator('.tile-hero');
    await expect(hero).toContainText('$200');
    await expect(hero).toContainText('+122.2% vs Oct 2025');
    await expect(page.getByText('Casey Clinic · harbourview')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Group' })).toHaveCount(0);
    await expect(page.getByRole('combobox', { name: 'Business' })).toHaveCount(0);
    await page.goto('/group');
    await expect(page.getByText('The group view is for people with the group permission')).toBeVisible();
  });
});

test.describe('OHIP', () => {
  test('tiles, provider table and the honest notice', async ({ page }) => {
    await signInAs(page, 'group', '/ohip');
    await expect(tile(page, 'Billed')).toContainText('$300');
    await expect(tile(page, 'Paid')).toContainText('$60');
    await expect(tile(page, 'Outstanding')).toContainText('$210');
    await expect(tile(page, 'Refused rate')).toContainText('10.0%');
    await expect(tile(page, 'Short-paid rate')).toContainText('3.3%');
    const provider = page.locator('section.card', { hasText: 'By provider' });
    await expect(provider.locator('tbody tr').nth(0)).toContainText('123456');
    await expect(provider.locator('tbody tr').nth(0)).toContainText('$300.00');
    await expect(provider.locator('tbody tr').nth(1)).toContainText('none');
    await expect(provider.locator('tbody tr').nth(1)).toContainText('$30.00');
    await expect(page.getByText('Days to pay is not shown')).toBeVisible();
  });

  test('the legend hides a series and the table twin stays complete', async ({ page }) => {
    await signInAs(page, 'group', '/ohip');
    const card = page.locator('section.card', { hasText: 'Billed and paid' });
    const paid = card.getByRole('button', { name: 'Paid' });
    await paid.click();
    await expect(paid).toHaveAttribute('aria-pressed', 'false');
    await card.getByRole('button', { name: 'Table' }).click();
    await expect(card.locator('thead')).toContainText('Paid');
    await expect(card.locator('tfoot')).toContainText('$60.00');
  });
});

test.describe('receivables', () => {
  test('ageing by payer type on the last snapshot of the range', async ({ page }) => {
    await signInAs(page, 'group', '/receivables');
    await expect(tile(page, 'Receivables outstanding')).toContainText('$260');
    await expect(tile(page, 'Over 30 days past due')).toContainText('$0');
    const card = page.locator('section.card', { hasText: 'Receivables by payer type and age' });
    await expect(card).toContainText('Open items on 2026-10-31');
    await card.getByRole('button', { name: 'Table' }).click();
    const ohip = card.locator('tbody tr', { hasText: 'OHIP' });
    await expect(ohip).toContainText('$200.00');
    await expect(ohip).toContainText('$10.00');
    await expect(card.locator('tbody tr', { hasText: 'Patient' })).toContainText('$50.00');
  });

  test('payables show the supplier that is 31 days past due', async ({ page }) => {
    await signInAs(page, 'group', '/receivables');
    await page.getByRole('button', { name: 'Payables' }).click();
    await expect(tile(page, 'Payables outstanding')).toContainText('$40');
    await expect(tile(page, 'Over 30 days past due')).toContainText('$40');
    await expect(tile(page, 'Share over 30 days')).toContainText('100.0%');
  });
});

test.describe('HST', () => {
  test('tiles from the journal, by month and by quarter', async ({ page }) => {
    await signInAs(page, 'group', '/hst');
    await expect(tile(page, 'Sales')).toContainText('$520');
    await expect(tile(page, 'HST collected')).toContainText('$13');
    await expect(tile(page, 'ITCs')).toContainText('$26');
    await expect(tile(page, 'Net tax refundable')).toContainText('$13');
    await expect(page.getByText('GST34 line numbers are not mapped')).toBeVisible();

    await page.getByRole('button', { name: 'By quarter' }).click();
    const card = page.locator('section.card', { hasText: 'Net tax by period' });
    await card.getByRole('button', { name: 'Table' }).click();
    await expect(card.locator('thead')).toContainText('2026 Q3');
    await expect(card.locator('thead')).toContainText('2026 Q4');
    const net = card.locator('tbody tr', { hasText: 'Net tax' });
    await expect(net).toContainText('$13.00');
    await expect(net).toContainText('-$26.00');
  });
});

test.describe('operations', () => {
  // From the synthetic events (tests/synthetic_events.py), all of October 2026:
  //   group: 9 placed, 6 with a result (45, 60, 60, 270, 600, 2880 min), 2 waiting, 1 cancelled
  //          median 165 min = 2 h 45 min, 90th percentile 1740 min = 1 d 5 h
  //   Harbourview alone: 8 placed, 5 resulted (45, 60, 270, 600, 2880): median 270 = 4 h 30 min, p90 1968 = 1 d 9 h
  test('a group user sees every clinic', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    await expect(tile(page, 'Orders placed')).toContainText('9');
    await expect(tile(page, 'With a final result')).toContainText('6');
    await expect(tile(page, 'Still waiting')).toContainText('2');
    await expect(tile(page, 'Median turnaround')).toContainText('2 h 45 min');
    await expect(tile(page, '90th percentile')).toContainText('1 d 5 h');
    await expect(tile(page, 'Cancelled')).toContainText('1');
    await expect(page.getByText('No patient is identifiable here')).toBeVisible();
  });

  test('a clinic user sees only their clinic', async ({ page }) => {
    await signInAs(page, 'clinic', '/operations');
    await expect(tile(page, 'Orders placed')).toContainText('8');
    await expect(tile(page, 'With a final result')).toContainText('5');
    await expect(tile(page, 'Median turnaround')).toContainText('4 h 30 min');
    await expect(tile(page, '90th percentile')).toContainText('1 d 9 h');
  });

  test('the department switch narrows everything below it', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    await page.getByRole('button', { name: 'Diagnostics' }).click();
    await expect(tile(page, 'Orders placed')).toContainText('1');
    await expect(tile(page, 'Median turnaround')).toContainText('2 d');
    await page.getByRole('button', { name: 'Lab', exact: true }).click();
    await expect(tile(page, 'Orders placed')).toContainText('8');
    await expect(tile(page, 'Median turnaround')).toContainText('1 h');
    await expect(tile(page, '90th percentile')).toContainText('7 h 48 min');
  });

  test('turnaround by test, in the table twin and in the CSV', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    const card = page.locator('section.card', { hasText: 'Turnaround by test' });
    await card.getByRole('button', { name: 'Table' }).click();
    const row = (code: string) => card.locator('tbody tr', { hasText: code });
    await expect(row('echo-tte')).toContainText('2 d');
    await expect(row('718-7')).toContainText('4 h 30 min'); // median of 60, 270, 600
    await expect(row('718-7')).toContainText('8 h 54 min'); // 90th percentile
    await expect(row('2160-0')).toContainText('53 min');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      card.getByRole('button', { name: 'Download CSV' }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('turnaround-by-test-2026-10.csv');
    const text = await readFile((await download.path()) as string, 'utf8');
    const lines = text.replace(/^\uFEFF/, '').split('\r\n');
    expect(lines[0]).toBe('Test code,Placed,With a result,Waiting,Cancelled,Median,90th percentile');
    // raw minutes, not "4 h 30 min": a spreadsheet can use them
    expect(lines.find((l) => l.startsWith('718-7,'))).toBe('718-7,6,3,2,1,270,534');
  });

  test('cancellations with what was refused', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    const card = page.locator('section.card', { hasText: 'Cancellations' });
    await expect(card).toContainText('1 cancelled and 1 refused by the lab');
    await card.getByRole('button', { name: 'Table' }).click();
    const lab = card.locator('tbody tr', { hasText: 'Lab' });
    await expect(lab).toContainText('Oct 2026');
    // the month is the row header: the cells are department, placed, cancelled, refused, share
    await expect(lab.locator('td').nth(1)).toHaveText('8');
    await expect(lab.locator('td').nth(2)).toHaveText('1');
    await expect(lab.locator('td').nth(3)).toHaveText('1');
    await expect(lab.locator('td').nth(4)).toHaveText('12.5%');
  });

  test('the business filter turns into a clinic', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    await page.getByRole('combobox', { name: 'Business' }).selectOption('HV');
    await expect(tile(page, 'Orders placed')).toContainText('8');
    await page.getByRole('combobox', { name: 'Business' }).selectOption('LAB');
    await expect(page.getByText('No orders placed in the selected months.')).toBeVisible();
  });

  test('hovering a bar of the turnaround chart gives the median and the 90th percentile', async ({ page }) => {
    await signInAs(page, 'group', '/operations');
    const card = page.locator('section.card', { hasText: 'Turnaround by test' });
    await card.getByLabel(/^echo-tte:/).hover();
    await expect(card.getByRole('tooltip')).toContainText('2 d');
    await expect(card.getByRole('tooltip')).toContainText('Median');
    await expect(card.getByRole('tooltip')).toContainText('90th percentile');
  });
});

test.describe('group', () => {
  test('businesses side by side', async ({ page }) => {
    await signInAs(page, 'group', '/group');
    const card = page.locator('section.card', { hasText: 'Businesses side by side' });
    await card.getByRole('button', { name: 'Table' }).click();
    await expect(card.locator('tbody tr').nth(0)).toContainText('Harbourview Clinic');
    await expect(card.locator('tbody tr').nth(0)).toContainText('$450.00');
    await expect(card.locator('tbody tr').nth(1)).toContainText('Group Lab');
    await expect(card.locator('tbody tr').nth(1)).toContainText('$70.00');
    // the page is about all businesses: no business filter here
    await expect(page.getByRole('combobox', { name: 'Business' })).toHaveCount(0);
  });
});

test.describe('CSV', () => {
  test('every table downloads as CSV with raw numbers', async ({ page }) => {
    await signInAs(page, 'group');
    const card = page.locator('section.card', { hasText: 'Revenue by line of business' });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      card.getByRole('button', { name: 'Download CSV' }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('revenue-by-line-of-business-2026-10.csv');
    const text = await readFile((await download.path()) as string, 'utf8');
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[0]).toBe('Line of business,Oct 2026,Oct 2025,Change,Change %');
    expect(lines[1]).toMatch(/^Clinic,200,90,110,1\.2222/);
    expect(lines[2]).toMatch(/^Lab,70,60,10,0\.1666/);
    expect(lines[3]).toMatch(/^Total,270,150,120,0\.8/);
  });

  test('the provider table has its own', async ({ page }) => {
    await signInAs(page, 'group', '/ohip');
    const card = page.locator('section.card', { hasText: 'By provider' });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      card.getByRole('button', { name: 'Download CSV' }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('ohip-by-provider-2026-10.csv');
  });
});

test.describe('look', () => {
  test('dark theme is chosen, applied and remembered', async ({ page }) => {
    await signInAs(page, 'group');
    const body = page.locator('body');
    await expect(body).toHaveCSS('background-color', 'rgb(249, 249, 247)');
    const toggle = page.getByRole('button', { name: /^Theme:/ });
    await toggle.click(); // system -> light
    await toggle.click(); // light -> dark
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(body).toHaveCSS('background-color', 'rgb(13, 13, 13)');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });

  test('follows the operating system when no theme was chosen', async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: 'dark' });
    const page = await context.newPage();
    await signInAs(page, 'group');
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(13, 13, 13)');
    await context.close();
  });

  for (const path of ['/', '/ohip', '/receivables', '/hst', '/operations']) {
    test(`${path} has no horizontal scroll on a phone`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width: 390, height: 800 } });
      const page = await context.newPage();
      await signInAs(page, 'clinic', path);
      await expect(page.locator('.card, .empty').first()).toBeVisible();
      await page.waitForTimeout(400);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await context.close();
    });
  }
});
