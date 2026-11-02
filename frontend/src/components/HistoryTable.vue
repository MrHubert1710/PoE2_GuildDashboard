<script setup lang="ts">
import CollapsiblePanel from './CollapsiblePanel.vue'
import { t, number, date } from '../i18n'
import type { HistoryQuery, TransactionPage } from '../browsing'
const props = defineProps<{ query: HistoryQuery; result: TransactionPage | null; loadingRows: boolean; rowError: string; timezone: string }>()
const emit = defineEmits<{ setPage: [value: number]; setPageSize: [value: number]; sortBy: [value: string] }>()
const setPage = (value: number) => emit('setPage', value)
const setPageSize = (value: number) => emit('setPageSize', value)
const sortBy = (value: string) => emit('sortBy', value)
const actionNames: Record<string, string> = { added: 'added', removed: 'removed', modified: 'modified' }
const columns = [{ key: 'date', label: 'dateColumn' }, { key: 'account', label: 'player' }, { key: 'action', label: 'quantity.sourceAction' }, { key: 'stash', label: 'stash' }, { key: 'item', label: 'item' }]
const leagueDate = (value: string | null) => date(value, props.timezone)
const signed = (value: number) => (value > 0 ? '+' : '') + number(value)
</script>
<template><CollapsiblePanel :title="t('layout.historyTable')" :storage-key="'history:'+query.league"><section class="history-view" :aria-label="t('history')">
        <div class="results-heading">

          <label>{{ t('pageSize') }}<select :aria-label="t('pageSize')" :value="query.page_size" @change="setPageSize(Number(($event.target as HTMLSelectElement).value))"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
        </div>
        <p v-if="loadingRows" role="status" class="loading-state">{{ t('loadingTransactions') }}</p>
        <p v-if="rowError" role="alert" class="alert">{{ t(rowError) }}</p>
        <div v-if="result" data-testid="transaction-results">
          <p class="result-count" role="status">{{ t('resultCount', { count: result.total, page: result.page, pages: result.pages }) }}</p>
          <p v-if="!result.rows.length" class="empty-state">{{ t('noTransactions') }}</p>
          <div v-else class="transactions-scroll" tabindex="0" role="region" :aria-label="t('tableRegion')">
            <table class="transactions history-transactions">
              <thead><tr>
                <th v-for="column in columns" :key="column.key" scope="col" :aria-sort="query.sort === column.key ? (query.direction === 'asc' ? 'ascending' : 'descending') : 'none'">
                  <button type="button" @click="sortBy(column.key)">{{ column.key === 'date' ? t('quantity.dateZone', { zone: timezone }) : t(column.label) }} <span v-if="query.sort === column.key" aria-hidden="true">{{ query.direction === 'asc' ? '↑' : '↓' }}</span></button>
                </th>
                <th scope="col">{{ t('quantity.delta') }}</th><th scope="col">{{ t('quantity.effectiveAction') }}</th>
                <th scope="col">{{ t('position') }}</th>
              </tr></thead>
              <tbody><tr v-for="row in result.rows" :key="row.id" :data-event-id="row.external_id">
                <td class="date-cell">{{ leagueDate(row.occurred_at) }}</td><td>{{ row.account }}</td>
                <td><span class="action" :class="row.action">{{ actionNames[row.action] ? t(actionNames[row.action]!) : row.action }}</span></td>
                <td>{{ row.stash }}</td><td class="item-cell">{{ row.item }}</td>
                <td class="quantity-delta">
                  <template v-if="row.quantity?.movements.length && row.quantity.movements.length > 1"><div v-for="(movement, index) in row.quantity.movements" :key="index">{{ signed(movement.quantity_delta) }} {{ movement.item_name }}</div></template>
                  <template v-else>{{ row.quantity?.quantity_delta !== null && row.quantity?.quantity_delta !== undefined ? signed(row.quantity.quantity_delta) : t('quantity.unknown') }}</template>
                </td>
                <td><template v-if="row.quantity"><span class="action" :class="row.quantity.effective_action">{{ t(`quantity.action.${row.quantity.effective_action}`) }}</span>
                  <details class="quantity-explanation"><summary>{{ t('quantity.explanation') }}</summary><p>{{ t(`quantity.reason.${row.quantity.resolution_reason}`) }}</p>
                    <p>{{ t('quantity.beforeAfter', { before: row.quantity.quantity_before === null ? t('quantity.unknown') : number(row.quantity.quantity_before), after: row.quantity.quantity_after === null ? t('quantity.unknown') : number(row.quantity.quantity_after) }) }}</p>
                    <p>{{ t(`quantity.confidence.${row.quantity.confidence}`) }}</p>
                  </details></template><span v-else>{{ t('quantity.pendingShort') }}</span></td>
                <td>{{ row.x }}, {{ row.y }}</td>
              </tr></tbody>
            </table>
          </div>
          <nav class="pagination" :aria-label="t('pages')">
            <button type="button" :disabled="loadingRows || result.page <= 1" @click="setPage(result.page - 1)">{{ t('previous') }}</button>
            <span>{{ result.page }} / {{ number(result.pages) }}</span>
            <button type="button" :disabled="loadingRows || result.page >= result.pages" @click="setPage(result.page + 1)">{{ t('next') }}</button>
          </nav>
        </div>

</section></CollapsiblePanel></template>
