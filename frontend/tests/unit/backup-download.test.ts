import test from 'node:test'
import assert from 'node:assert/strict'
import {attachmentFilename,backupDownloadFilename} from '../../src/lib/backupDownload.ts'

test('report and workbook downloads share safe unquoted, quoted and UTF-8 filename parsing', () => {
  const file = 'authlens-sod-reference-template.xlsx'
  for (const header of [`attachment; filename=${file}`, `attachment; filename="${file}"`, `attachment; filename*=UTF-8''${file}`]) assert.equal(attachmentFilename(header), file)
  for (const header of ['attachment; filename=../secret.xlsx', "attachment; filename*=UTF-8''..%2Fsecret.xlsx", 'attachment; filename*=UTF-8\'\'%zz']) assert.equal(attachmentFilename(header), undefined)
})

const id = 'a'.repeat(32)
const name = `AuthLens-backup-${id}.slbak`
test('backup downloads accept ASP.NET unquoted, quoted and UTF-8 disposition filenames', () => {
  for (const header of [`attachment; filename=${name}; filename*=UTF-8''${name}`, `attachment; filename="${name}"`, `attachment; filename=${name}`, `attachment; filename*=UTF-8''${encodeURIComponent(name)}`]) {
    assert.equal(backupDownloadFilename(header, 'backup', id), name)
  }
  assert.equal(backupDownloadFilename(`attachment; filename=AuthLens-destination-before-restore-${id}.slbak`, 'destination-before-restore', id), `AuthLens-destination-before-restore-${id}.slbak`)
})
test('backup downloads refuse missing, malformed, mismatched and traversal filenames', () => {
  for (const header of [null, '', 'attachment; filename=../../host.key', `attachment; filename="../${name}"`, `attachment; filename=${name.replace(id, 'b'.repeat(32))}`, `attachment; filename*=UTF-8''%zz`]) {
    assert.throws(() => backupDownloadFilename(header, 'backup', id), /Invalid backup filename/)
  }
  assert.throws(() => backupDownloadFilename(`attachment; filename=${name}`, 'backup', '../data'), /Invalid backup identifier/)
  assert.throws(() => backupDownloadFilename(`attachment; filename=${name}`, 'unknown', id), /Invalid backup identifier/)
})
