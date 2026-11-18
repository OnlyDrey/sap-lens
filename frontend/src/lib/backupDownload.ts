/** Accept ASP.NET's RFC 6266 filename forms, but only the expected safe archive name. */
export function backupDownloadFilename(disposition: string | null, kind: string, identity: string): string {
  if (identity.length !== 32 || !/^[a-f0-9]{32}$/.test(identity) || !['backup', 'destination-before-restore'].includes(kind)) throw Error('Invalid backup identifier.')
  const extended = disposition?.match(/(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]*)/i)
  const ordinary = disposition?.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;\s]*))/i)
  let name: string | undefined
  try { name = extended ? decodeURIComponent(extended[1].trim()) : ordinary?.[1] ?? ordinary?.[2] } catch { throw Error('Invalid backup filename.') }
  if (name !== `SAP-Lens-${kind}-${identity}.slbak` && name !== `SAP-Lens-${kind}-${identity}.tar.gz`) throw Error('Invalid backup filename.')
  return name
}
