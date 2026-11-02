// Plain text only; Vue escapes the returned message and every interpolated value.
export function formatMessage(catalogs, locale, key, parameters = {}) {
  const message = catalogs[locale]?.messages[key] ?? catalogs.en.messages[key]
  if (!message) return key
  const template = typeof message === 'string' ? message : message[new Intl.PluralRules(locale).select(Number(parameters.count))] ?? message.other
  return template.replace(/\{([a-zA-Z][\w]*)\}/g, (_, name) => {
    const value = parameters[name]
    return typeof value === 'number' ? new Intl.NumberFormat(locale).format(value) : value ?? `{${name}}`
  })
}
