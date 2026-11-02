export type Message = string | Record<string, string>
export interface Catalog { nativeName: string; messages: Record<string, Message> }
export function validateCatalog(files: Record<string, unknown>): Record<string, Catalog>
export function loadCatalog(directory: string): Record<string, Catalog>
