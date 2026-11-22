import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeLead } from '/tmp/test-app/src/lib/validation.ts'

test('isolated test environment imports the restored program', () => {
  assert.equal(typeof normalizeLead, 'function')
})
