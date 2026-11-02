<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import CollapsiblePanel from './CollapsiblePanel.vue'
import { t } from '../i18n'
import type { HistoryQuery } from '../browsing'
import TextFilter from './TextFilter.vue'
import StashFilter from './StashFilter.vue'
defineProps<{ draft: HistoryQuery; stashes: string[]; formError: string; timezone: string }>()
const panel=ref<InstanceType<typeof CollapsiblePanel>|null>(null)
let observer:ResizeObserver|undefined
onMounted(()=>{observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--filters-height',Math.ceil((panel.value?.$el as HTMLElement)?.getBoundingClientRect().height??0)+'px'));if(panel.value?.$el)observer.observe(panel.value.$el)})
onUnmounted(()=>observer?.disconnect())
const emit = defineEmits<{ apply: []; clear: [] }>()
</script>
<template><CollapsiblePanel ref="panel" class="workspace-filters" :title="t('workspace.filters')" :storage-key="'filters'" :aria-label="t('workspace.filters')">
        <form class="filters" @submit.prevent="emit('apply')">
          <TextFilter v-model="draft.account" v-model:regex="draft.account_regex" v-model:match-case="draft.account_case" v-model:whole-word="draft.account_word" name="account" :label="t('player')" :placeholder="t('accountPlaceholder')" />
          <StashFilter v-model="draft.stash" :options="stashes" />
          <TextFilter class="filter-item" v-model="draft.item" v-model:regex="draft.item_regex" v-model:match-case="draft.item_case" v-model:whole-word="draft.item_word" name="item" :label="t('item')" :placeholder="t('itemPlaceholder')" />
          <label>{{ t('fromDayZone',{zone:timezone}) }}<input v-model="draft.from" name="from" type="date" /></label>
          <label>{{ t('toDayZone',{zone:timezone}) }}<input v-model="draft.to" name="to" type="date" /></label>
          <div class="filter-actions"><button class="primary" type="submit">{{ t('applyFilters') }}</button><button type="button" @click="emit('clear')">{{ t('clearFilters') }}</button></div>
        </form>
        <p v-if="formError" role="alert" class="alert">{{ t(formError) }}</p>
</CollapsiblePanel></template>
