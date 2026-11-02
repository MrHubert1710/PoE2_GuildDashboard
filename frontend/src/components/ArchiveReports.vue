<script setup lang="ts">
import { t } from '../i18n'
import type { League } from '../browsing'
defineProps<{ selected: League }>()
const archiveUrl = (id: number) => `${import.meta.env.BASE_URL}archives/${id}`
</script>
<template>
        <section class="historical-reports" aria-labelledby="reports-title">
          <div class="section-heading"><h2 id="reports-title">{{ t('reportsTitle') }}</h2><span>{{ selected.name }}</span></div>
          <p v-if="!selected.reports.length" class="footnote">{{ t('noReports') }}</p>
          <div v-else class="report-links"><a v-for="report in selected.reports" :key="report.id" :href="archiveUrl(report.id)" target="_blank" rel="noopener noreferrer">{{ report.name.split('/').at(-1) }} <span>{{ report.sha256.slice(0, 8) }} · ↗</span></a></div>
          <p class="footnote">{{ t('reportsNote') }}</p>
        </section>
</template>
