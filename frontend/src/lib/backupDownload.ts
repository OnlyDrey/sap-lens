/** Parse ASP.NET's RFC 6266 forms without accepting path separators or control characters. Callers still require their exact filename pattern. */
export function attachmentFilename(disposition: string | null): string | undefined {
  const extended = disposition?.match(/(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]*)/i)
  const ordinary = disposition?.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;\s]*))/i)
  let name: string | undefined
  try { name = extended ? decodeURIComponent(extended[1].trim()) : ordinary?.[1] ?? ordinary?.[2] } catch { return undefined }
  return name && !/[\\/:]/.test(name) && ![...name].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127) ? name : undefined
}

/** Accept only the expected safe archive name. */
export function backupDownloadFilename(disposition: string | null, kind: string, identity: string): string {
  if (identity.length !== 32 || !/^[a-f0-9]{32}$/.test(identity) || !['backup', 'destination-before-restore'].includes(kind)) throw Error('Invalid backup identifier.')
  const name = attachmentFilename(disposition)
  if (name !== `AuthLens-${kind}-${identity}.slbak` && name !== `AuthLens-${kind}-${identity}.tar.gz`) throw Error('Invalid backup filename.')
  return name
}
