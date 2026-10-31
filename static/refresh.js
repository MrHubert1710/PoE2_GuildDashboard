(() => {
    'use strict';
    const initial = JSON.parse(document.getElementById('refresh-bootstrap').textContent);
    const pill = document.getElementById('refresh-pill');
    const banner = document.getElementById('refresh-error');
    const contextKey = 'poe2logger-refresh-context';
    const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));
    const label = button => button.querySelector('.subtab-label')?.textContent.trim();
    const panelKey = panel => {
        const tab = panel.closest('.tab-panel');
        const button = all('.subtab-button', tab).find(b => b.dataset.subtabTarget === panel.id);
        return [tab.id, label(button || panel)];
    };
    function saveContext() {
        const context = {
            tab: document.querySelector('.tab-button.active')?.dataset.tab,
            sub: all('.subtab-button.active').map(b => [b.closest('.tab-panel').id, label(b)]),
            views: all('.subtab-panel').map(p => [panelKey(p), p.querySelector('.view-button.active')?.dataset.view]),
            tables: all('table').map(t => ({
                panel: t.closest('.subtab-panel') ? panelKey(t.closest('.subtab-panel')) : [t.closest('.tab-panel')?.id],
                view: t.closest('.view-panel')?.dataset.viewPanel,
                index: all('table', t.closest('.view-panel') || t.closest('.tab-panel')).indexOf(t),
                filter: t.closest('.table-scroll')?.previousElementSibling?.querySelector('input')?.value,
                column: t.dataset.sortColumn, sort: t.dataset.sortState,
                scroll: t.closest('.table-scroll')?.scrollTop,
            })),
            nav: all('.subtab-nav').map(n => [n.closest('.tab-panel').id, n.scrollTop]),
            x: window.scrollX, y: window.scrollY,
        };
        try { sessionStorage.setItem(contextKey, JSON.stringify(context)); } catch (_) { /* storage disabled */ }
    }
    function restoreContext() {
        let context;
        try {
            context = JSON.parse(sessionStorage.getItem(contextKey));
            sessionStorage.removeItem(contextKey);
        } catch (_) { return; }
        if (!context) return;
        all('.tab-button').find(b => b.dataset.tab === context.tab)?.click();
        for (const [tab, name] of context.sub) {
            const panel = document.getElementById(tab);
            if (panel) all('.subtab-button', panel).find(b => label(b) === name)?.click();
        }
        for (const [key, view] of context.views) {
            const panel = all('.subtab-panel').find(p => JSON.stringify(panelKey(p)) === JSON.stringify(key));
            if (panel) all('.view-button', panel).find(b => b.dataset.view === view)?.click();
        }
        for (const saved of context.tables) {
            const panel = saved.panel.length === 2
                ? all('.subtab-panel').find(p => JSON.stringify(panelKey(p)) === JSON.stringify(saved.panel))
                : document.getElementById(saved.panel[0]);
            if (!panel) continue;
            const root = saved.view ? all('.view-panel', panel).find(p => p.dataset.viewPanel === saved.view) : panel;
            if (!root) continue;
            const table = all('table', root)[saved.index];
            if (!table) continue;
            if (typeof applyTableSort === 'function') {
                applyTableSort(table, Number(saved.column || 0), saved.sort || 'normal', false);
            }
            const input = table.closest('.table-scroll')?.previousElementSibling?.querySelector('input');
            if (input && saved.filter) {
                input.value = saved.filter;
                input.dispatchEvent(new Event('input'));
            }
            if (table.closest('.table-scroll')) table.closest('.table-scroll').scrollTop = saved.scroll || 0;
        }
        for (const [tab, top] of context.nav) {
            const nav = document.getElementById(tab)?.querySelector('.subtab-nav');
            if (nav) nav.scrollTop = top;
        }
        requestAnimationFrame(() => window.scrollTo(context.x, context.y));
    }
    restoreContext();
    const url = new URL(location.href);
    url.searchParams.delete('__snapshot');
    history.replaceState(history.state, '', url);
    let reloading = false;
    function update(state) {
        banner.hidden = !state.failed;
        pill.disabled = state.running;
        const stamp = state.last_success ? new Date(state.last_success).toLocaleString() : 'unknown';
        pill.textContent = `${state.running ? 'Refreshing… · ' : ''}Last refresh: ${stamp}`;
        if (state.revision !== initial.revision && !reloading) {
            reloading = true;
            saveContext();
            const target = new URL(location.href);
            target.searchParams.set('__snapshot', '1');
            location.replace(target);
        }
    }
    update(initial);
    async function poll() {
        try {
            const response = await fetch(initial.status_url, {cache: 'no-store'});
            if (response.ok) update(await response.json());
        } catch (_) { /* Retry after a temporary connection interruption. */ }
        if (!reloading) setTimeout(poll, 3000);
    }
    pill.addEventListener('click', async () => {
        pill.disabled = true;
        try {
            const response = await fetch(initial.refresh_url, {
                method: 'POST', headers: {'X-Requested-With': 'Poe2Logger'}, cache: 'no-store',
            });
            if (!response.ok) throw new Error('Refresh failed');
            update(await response.json());
        } catch (_) {
            banner.hidden = false;
            pill.disabled = false;
        }
    });
    poll();
})();
