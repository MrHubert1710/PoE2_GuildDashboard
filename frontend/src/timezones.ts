import aliases from '../../shared/timezone-aliases.json'

export function timezoneSuggestions() {
  return [
    ...Object.entries(aliases).map(([value, offset]) => ({ value, label: `${value} (${offset})` })),
    ...Array.from({ length: 29 }, (_, index) => {
      const hour = index - 14
      const value = hour === 0 ? 'UTC+0' : `UTC${hour > 0 ? '+' : ''}${hour}`
      return { value, label: value }
    }),
    ...Intl.supportedValuesOf('timeZone').map(value => ({ value, label: value })),
  ]
}

export function formatZonedDate(value: string, locale: string, timeZone: string) {
  const input = timeZone.trim()
  const zone = (aliases as Record<string, string>)[input.toUpperCase()] ?? input
  const offset = /^UTC\s*([+-])\s*(\d{1,2})(?:(?::(\d{2}))|(\.\d{1,2}))?$/i.exec(zone)
  let date = new Date(value)
  let target = zone
  if (offset) {
    const minutes = Number(offset[2]) * 60 + (offset[4] ? Number(offset[4]) * 60 : Number(offset[3] ?? 0))
    if (minutes > 840 || !Number.isInteger(minutes) || Number(offset[3] ?? 0) >= 60) throw new RangeError('invalid_timezone')
    date = new Date(date.getTime() + (offset[1] === '+' ? 1 : -1) * minutes * 60000)
    target = 'UTC'
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: target }).format(date)
}
