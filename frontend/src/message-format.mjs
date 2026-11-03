// Keep grouped digits together when a label wraps, independently of locale.
export function formatNumber(value, locale, options = {}) {
  return new Intl.NumberFormat(locale, options).formatToParts(value)
    .map(part => part.type === 'group' ? '\u00a0' : part.value).join('')
}

// Plain text only; Vue escapes the returned message and every interpolated value.
export function formatMessage(catalogs, locale, key, parameters = {}) {
  const message = catalogs[locale]?.messages[key] ?? catalogs.en.messages[key]
  if (!message) return key
  const template = typeof message === 'string' ? message : message[new Intl.PluralRules(locale).select(Number(parameters.count))] ?? message.other
  return template.replace(/\{([a-zA-Z][\w]*)\}/g, (_, name) => {
    const value = parameters[name]
    return typeof value === 'number' ? formatNumber(value, locale) : value ?? `{${name}}`
  })
}
