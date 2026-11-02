<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, AriaComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import type { SeriesPoint } from '../composables/useQuantitySeries'
import { t, date, number, locale } from '../i18n'
echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, AriaComponent, SVGRenderer])
const props = defineProps<{ points: SeriesPoint[]; bounds: { start: number; end: number }; timezone: string; enabled: string[]; window: {start: number; end: number} | null }>()
const emit = defineEmits<{ zoom: [window: {start: number; end: number}] }>()
const root = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | undefined, observer: ResizeObserver | undefined
function draw() {
  if (!root.value || !root.value.clientWidth || !root.value.clientHeight) return
  if (!chart) {
    chart = echarts.init(root.value, undefined, { renderer: 'svg' })
    chart.on('datazoom', () => {
      const zoom = (chart!.getOption().dataZoom as Array<{ start: number; end: number }>)[0]!
      const width = props.bounds.end - props.bounds.start
      emit('zoom', { start: Math.round(props.bounds.start + width * zoom.start / 100), end: Math.round(props.bounds.start + width * zoom.end / 100) })
    })
  }
  const start = props.window?.start ?? props.bounds.start, end = props.window?.end ?? props.bounds.end
  const options: EChartsOption = {
    animation: false, backgroundColor: 'transparent', textStyle: { color: '#b7c4ca', fontFamily: 'system-ui' },
    aria: { enabled: true, description: t('chart.graph') },
    grid: { left: 54, right: 22, top: 22, bottom: 100 },
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true, valueFormatter: value => number(Number(value)),
      axisPointer: { type: 'cross', label: { formatter: params => params.axisDimension === 'x' ? date(new Date(Number(params.value)).toISOString(), props.timezone) : number(Number(params.value)) } } },
    xAxis: { type: 'time', min: props.bounds.start, max: props.bounds.end,
      axisLabel: { color: '#b7c4ca', hideOverlap: true, formatter: value => date(new Date(value).toISOString(), props.timezone) }, axisLine: { lineStyle: { color: '#46545e' } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#b7c4ca', formatter: value => number(value) }, splitLine: { lineStyle: { color: '#29363e' } } },
    dataZoom: [{ type: 'inside', startValue: start, endValue: end, filterMode: 'none' },
      { type: 'slider', startValue: start, endValue: end, bottom: 20, height: 28, showDetail: false, borderColor: '#46545e' }],
    series: [
      { id: 'added', name: t('added'), color: '#a7d9b2' },
      { id: 'removed', name: t('removed'), color: '#edaa92' },
      { id: 'net', name: t('quantity.balance'), color: '#8ebce7' },
    ].filter(series => props.enabled.includes(series.id)).map(series => ({ ...series, type: 'line', showSymbol: props.points.length < 10,
      lineStyle: { width: 2 }, data: props.points.map(point => [point.timestamp, series.id === 'removed' ? -point.removed : point[series.id as 'added' | 'net']]) })),
  }
  chart.setOption(options, { notMerge: true, silent: true })
  chart.resize()
  root.value.querySelector('svg')?.setAttribute('aria-hidden', 'true')
}
function zoomIn() {
  const start = props.window?.start ?? props.bounds.start, end = props.window?.end ?? props.bounds.end
  const quarter = (end - start) / 4
  emit('zoom', { start: Math.round(start + quarter), end: Math.round(end - quarter) })
}
defineExpose({ zoomIn })
watch(() => [props.points,props.bounds,props.enabled,props.window,props.timezone,locale.value], () => { void nextTick(draw) }, { deep: true })
onMounted(() => {
  observer = new ResizeObserver(() => { if (root.value?.clientWidth) draw() })
  if (root.value) observer.observe(root.value)
  draw()
})
onUnmounted(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template><div ref="root" class="time-series-chart" role="img" :aria-label="t('chart.graph')" data-testid="time-series-chart"></div></template>
