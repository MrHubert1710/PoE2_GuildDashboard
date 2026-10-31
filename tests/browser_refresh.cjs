// Uses the bundled Playwright runtime. All network traffic is mocked.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
    console.log('Launching browser refresh checks...');
    const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || undefined});
    console.log('Browser started.');
    try {
        const context = await browser.newContext();
        let state = {revision: 'one', running: false, failed: false, last_success: '2026-10-31T10:00:00Z'};
        let manual = 0;
        const python = process.env.TEST_PYTHON || 'python';
        const fixture = path.join(__dirname, 'browser_fixture.py');
        const originalSource = execFileSync(python, [fixture], {encoding: 'utf8'});
        const updatedSource = execFileSync(python, [fixture, '--new-player'], {encoding: 'utf8'});
        const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'refresh.js'), 'utf8');
        await context.route('http://poe2logger.test/**', async route => {
            const url = new URL(route.request().url());
            if (url.pathname === '/api/refresh-status') return route.fulfill({json: state});
            if (url.pathname === '/api/refresh') {
                manual++;
                state = {...state, running: true};
                return route.fulfill({json: state});
            }
            if (url.pathname === '/refresh.js') {
                return route.fulfill({contentType: 'text/javascript', body: script});
            }
            const bootstrap = {...state, status_url: '/api/refresh-status', refresh_url: '/api/refresh'};
            const source = state.revision === 'one' ? originalSource : updatedSource;
            const body = source.replace('<body>', '<body><div id="refresh-error" hidden></div><button id="refresh-pill"></button>')
                .replace('</body>', `<script id="refresh-bootstrap" type="application/json">${JSON.stringify(bootstrap)}</script><script src="/refresh.js"></script></body>`);
            return route.fulfill({contentType: 'text/html', body});
        });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto('http://poe2logger.test/');
        await page.locator('.tab-button[data-tab="by-player"]').click();
        const selection = page.locator('#by-player .subtab-button').nth(1);
        const selectedName = await selection.locator('.subtab-label').textContent();
        await selection.click();
        const active = page.locator('#by-player .subtab-panel.active');
        await active.locator('.view-button[data-view="log"]').click();
        const input = active.locator('.view-panel[data-view-panel="log"] input');
        await input.fill('Orb');
        await active.locator('.view-panel[data-view-panel="log"] th').first().click();
        const beforeSort = await active.locator('.view-panel[data-view-panel="log"] table').getAttribute('data-sort-state');
        const second = await context.newPage();
        await second.goto('http://poe2logger.test/');
        const firstReload = page.waitForEvent('load');
        const secondReload = second.waitForEvent('load');
        state = {...state, revision: 'two', last_success: '2026-10-31T11:00:00Z'};
        await Promise.all([firstReload, secondReload]);
        assert.equal(await page.locator('.tab-button.active').getAttribute('data-tab'), 'by-player');
        assert.equal(await page.locator('#by-player .subtab-button.active .subtab-label').textContent(), selectedName);
        assert.equal(await active.locator('.view-button.active').getAttribute('data-view'), 'log');
        assert.equal(await input.inputValue(), 'Orb');
        assert.equal(await active.locator('.view-panel[data-view-panel="log"] table').getAttribute('data-sort-state'), beforeSort);
        assert.equal(new URL(page.url()).searchParams.has('__snapshot'), false);
        assert.equal(await second.locator('.tab-button.active').getAttribute('data-tab'), 'totals');
        state = {...state, failed: true};
        await page.waitForFunction(() => !document.getElementById('refresh-error').hidden);
        await page.locator('#refresh-pill').click();
        await page.waitForFunction(() => document.getElementById('refresh-pill').disabled);
        assert.equal(manual, 1);
        state = {...state, revision: 'three', running: false, failed: false};
        await page.waitForEvent('load');
        assert.equal(await input.inputValue(), 'Orb');
        assert.equal(await page.locator('#refresh-error').isHidden(), true);
        assert.deepEqual(errors, []);
        console.log('Browser checks passed: two clients, stable selection, view, filter, sort, manual refresh, failure and recovery.');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
