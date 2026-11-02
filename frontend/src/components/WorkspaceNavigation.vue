<script setup lang="ts">
import { section, workspaceSections, sectionUrl, navigateSection } from '../navigation'
import { t } from '../i18n'
</script>

<template>
  <nav class="workspace-nav" :aria-label="t('workspace.navigation')">
    <a v-for="target in workspaceSections" :key="target" :href="sectionUrl(target).pathname + sectionUrl(target).search"
      :aria-current="section === target ? 'page' : undefined" @click.prevent="navigateSection(target)">{{ t(`workspace.section.${target}`) }}</a>
  </nav>
</template>
