import { after, before, beforeEach, describe, test } from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { spawnSync } from 'node:child_process'

// Spec-compliance tests for the shared submitLead pipeline, the npm submit CLI, and the build.
// Runs against the disposable copy at /tmp/test-app.

const APP = '/tmp/test-app'
const OUT = path.join(APP, 'output')
const INPUT_FILE = path.join(APP, 'src/data/lead_input.json')
const LEDGERS = ['crm_leads.json', 'incomplete_leads.json', 'lead_sources.json', 'reconciliation.json']
const OUTPUT_KEYS = [
  'fullName', 'email', 'phone', 'service', 'city', 'state', 'consent',
  'source', 'campaign', 'utmMedium', 'submittedAt', 'status',
]

interface Result {
  status: string
  payload?: any
  missingFields?: string[]
  reason?: string
}

let submitLead: (input: unknown) => Promise<Result>

before(async () => {
  ;({ submitLead } = await import(path.join(APP, 'src/lib/submitLead.ts')))
})

function resetOutput(): void {
  fs.rmSync(OUT, { recursive: true, force: true })
  fs.mkdirSync(OUT, { recursive: true })
}

beforeEach(resetOutput)

const file = (name: string): string => path.join(OUT, name)
const exists = (name: string): boolean => fs.existsSync(file(name))
const raw = (name: string): string => fs.readFileSync(file(name), 'utf8')
const read = (name: string): any => JSON.parse(raw(name))
const readRejected = (): Array<{ path: string; reason: string }> =>
  exists('rejected_ledgers.json') ? read('rejected_ledgers.json') : []

function seed(name: string, value: unknown): void {
  const text = typeof value === 'string' ? value : `${JSON.stringify(value, null, 2)}\n`
  fs.writeFileSync(file(name), text)
}

function snapshot(names: string[] = LEDGERS): Record<string, string | null> {
  return Object.fromEntries(names.map(name => [name, exists(name) ? raw(name) : null]))
}

const complete: Record<string, unknown> = {
  fullName: 'Jane Carter',
  email: 'jane.carter@example.com',
  phone: '+14045550129',
  service: 'window_replacement',
  city: 'Atlanta',
  state: 'GA',
  consent: true,
  receivedAt: '2025-01-02T15:30:00Z',
}

const lead = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({ ...complete, ...overrides })

function withoutCity(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const { city: _city, ...rest } = complete
  return { ...rest, ...overrides }
}

const googleAds = (overrides: Record<string, unknown> = {}): Record<string, unknown> =>
  lead({
    source: 'google_ads',
    campaign: 'spring-window-leads',
    utmMedium: 'cpc',
    gclid: 'GCLID-SAMPLE-001',
    landingPage: '/window-replacement?gclid=GCLID-SAMPLE-001',
    ...overrides,
  })

function facebookLead(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    platform: 'facebook_lead_ads',
    leadgen_id: 'LG-1001',
    form_id: 'FORM-9',
    ad_id: 'AD-7',
    campaign_id: 'CAMP-42',
    consent: true,
    receivedAt: '2025-01-02T15:30:00Z',
    field_data: [
      { name: 'full_name', values: ['Jane Carter'] },
      { name: 'email', values: ['jane.carter@example.com'] },
      { name: 'phone_number', values: ['+14045550129'] },
      { name: 'service_needed', values: ['Windows'] },
      { name: 'city', values: ['Atlanta'] },
      { name: 'state', values: ['ga'] },
    ],
    ...overrides,
  }
}

describe('accepted website lead', () => {
  test('writes submission, CRM, sources, and reconciliation outputs', async () => {
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.equal(r.payload.status, 'ready_for_crm')
    for (const name of ['submission.json', 'crm_leads.json', 'lead_sources.json', 'reconciliation.json']) {
      assert.ok(exists(name), `${name} should be written`)
    }
    assert.deepEqual(read('submission.json'), r.payload)
    assert.deepEqual(read('crm_leads.json'), [r.payload])
  })

  test('saved record uses exactly the outputKeys set', async () => {
    await submitLead(complete)
    const [saved] = read('crm_leads.json')
    assert.deepEqual(Object.keys(saved).sort(), [...OUTPUT_KEYS].sort())
  })

  test('keeps submitted email and customer text; normalizes state and service', async () => {
    const r = await submitLead(lead({ email: 'Jane.Carter@Example.com', state: 'ga', service: 'Windows' }))
    assert.equal(r.status, 'accepted')
    assert.equal(r.payload.email, 'Jane.Carter@Example.com')
    assert.equal(r.payload.fullName, 'Jane Carter')
    assert.equal(r.payload.state, 'GA')
    assert.equal(r.payload.service, 'window_replacement')
  })

  test('applies default source, campaign, and utmMedium', async () => {
    const r = await submitLead(complete)
    assert.equal(r.payload.source, 'website')
    assert.equal(r.payload.campaign, 'direct')
    assert.equal(r.payload.utmMedium, 'organic')
  })

  test('drops attribution fields the website source does not keep', async () => {
    const r = await submitLead(lead({ gclid: 'GCLID-X', landingPage: '/x' }))
    assert.equal(r.status, 'accepted')
    assert.equal('gclid' in r.payload, false)
    assert.equal('landingPage' in r.payload, false)
  })

  test('uses the fallback receivedAt when none is supplied', async () => {
    const { receivedAt: _receivedAt, ...rest } = complete
    const r = await submitLead(rest)
    assert.equal(r.payload.submittedAt, '2025-01-02T10:00:00Z')
  })

  test('same input produces byte-identical outputs on repeat runs (deterministic)', async () => {
    await submitLead(complete)
    const first = snapshot()
    resetOutput()
    await submitLead(complete)
    assert.deepEqual(snapshot(), first)
  })
})

const timestampCases: Array<[string, string, string]> = [
  ['in-hours Thursday keeps receivedAt', '2025-01-02T15:30:00Z', '2025-01-02T15:30:00Z'],
  ['before opening moves to 09:00 same day', '2025-01-02T08:00:00Z', '2025-01-02T09:00:00Z'],
  ['after cutoff rolls to next business day open', '2025-01-02T18:45:10Z', '2025-01-03T09:00:00Z'],
  ['Saturday rolls to Monday open', '2025-01-04T12:00:00Z', '2025-01-06T09:00:00Z'],
  ['holiday rolls to next business day open', '2025-01-01T12:00:00Z', '2025-01-02T09:00:00Z'],
  ['MLK holiday Monday rolls to Tuesday open', '2025-01-20T12:00:00Z', '2025-01-21T09:00:00Z'],
  ['offset timestamp is converted to UTC', '2025-01-02T10:00:00-05:00', '2025-01-02T15:00:00Z'],
  ['fractional seconds are dropped', '2025-01-02T15:30:00.250Z', '2025-01-02T15:30:00Z'],
]

describe('deterministic UTC timestamping (business_calendar.json)', () => {
  for (const [name, receivedAt, expected] of timestampCases) {
    test(`${name} (${receivedAt} -> ${expected})`, async () => {
      const r = await submitLead(lead({ receivedAt }))
      assert.equal(r.status, 'accepted')
      assert.equal(r.payload.submittedAt, expected)
      assert.equal(read('crm_leads.json')[0].submittedAt, expected)
    })
  }
})

describe('rejected leads', () => {
  const rejectionCases: Array<[string, Record<string, unknown>]> = [
    ['malformed email', lead({ email: 'jane.example.com' })],
    ['disposable email domain', lead({ email: 'jane@mailinator.com' })],
    ['consent declined', lead({ consent: false })],
    ['consent missing', lead({ consent: undefined })],
    ['phone without leading +', lead({ phone: '4045550129' })],
    ['state outside allowedStates', lead({ state: 'ZZ' })],
    ['unknown service', lead({ service: 'plumbing' })],
    ['non-text fullName', lead({ fullName: ['Jane'] })],
  ]

  for (const [name, input] of rejectionCases) {
    test(`${name} is rejected, writes no ledgers, and removes stale submission.json`, async () => {
      seed('submission.json', { stale: true })
      const r = await submitLead(input)
      assert.equal(r.status, 'rejected')
      assert.equal(typeof r.reason, 'string')
      assert.equal(exists('submission.json'), false)
      assert.equal(exists('crm_leads.json'), false)
      assert.equal(exists('incomplete_leads.json'), false)
    })
  }

  test('rejection leaves existing ledgers byte-for-byte unchanged', async () => {
    await submitLead(complete)
    const before = snapshot()
    const r = await submitLead(lead({ email: 'bad-email' }))
    assert.equal(r.status, 'rejected')
    assert.deepEqual(snapshot(), before)
    assert.equal(exists('submission.json'), false)
  })
})

describe('incomplete (needs_review) leads', () => {
  test('missing city is stored for review with missingFields and writes no accepted submission', async () => {
    const r = await submitLead(withoutCity())
    assert.equal(r.status, 'needs_review')
    assert.deepEqual(r.missingFields, ['city'])
    const [entry] = read('incomplete_leads.json')
    assert.equal(entry.status, 'needs_review')
    assert.deepEqual(entry.missingFields, ['city'])
    assert.equal(exists('submission.json'), false)
    assert.ok(exists('lead_sources.json'))
    assert.ok(exists('reconciliation.json'))
  })

  test('reports every missing CRM field', async () => {
    const r = await submitLead(lead({ phone: undefined, city: undefined }))
    assert.equal(r.status, 'needs_review')
    assert.deepEqual([...(r.missingFields ?? [])].sort(), ['city', 'phone'])
    assert.deepEqual([...read('incomplete_leads.json')[0].missingFields].sort(), ['city', 'phone'])
  })

  test('a stale submission.json is removed for a needs_review lead', async () => {
    seed('submission.json', { stale: true })
    const r = await submitLead(withoutCity())
    assert.equal(r.status, 'needs_review')
    assert.equal(exists('submission.json'), false)
  })
})

describe('legacy-schema leads', () => {
  const legacy = {
    name: 'Jane Carter',
    email: 'jane.carter@example.com',
    phoneNumber: '+14045550129',
    serviceCode: 'windows',
    municipality: 'Atlanta',
    region: 'ga',
    acceptedTerms: true,
    origin: 'website',
    campaignName: 'legacy-campaign',
    medium: 'email',
    capturedAt: '2025-01-02T15:30:00Z',
  }

  test('maps every legacy field name onto the intake field names', async () => {
    const r = await submitLead(legacy)
    assert.equal(r.status, 'accepted')
    assert.equal(r.payload.fullName, 'Jane Carter')
    assert.equal(r.payload.phone, '+14045550129')
    assert.equal(r.payload.service, 'window_replacement')
    assert.equal(r.payload.city, 'Atlanta')
    assert.equal(r.payload.state, 'GA')
    assert.equal(r.payload.consent, true)
    assert.equal(r.payload.source, 'website')
    assert.equal(r.payload.campaign, 'legacy-campaign')
    assert.equal(r.payload.utmMedium, 'email')
    assert.equal(r.payload.submittedAt, '2025-01-02T15:30:00Z')
  })

  test('canonical field names win when both legacy and canonical are present', async () => {
    const r = await submitLead({ ...legacy, fullName: 'Canonical Name' })
    assert.equal(r.payload.fullName, 'Canonical Name')
  })
})

describe('Facebook webhook leads', () => {
  test('maps leadgen payload, field_data (first value), and attribution keys', async () => {
    const r = await submitLead(facebookLead())
    assert.equal(r.status, 'accepted')
    assert.equal(r.payload.source, 'facebook_lead_ads')
    assert.equal(r.payload.utmMedium, 'paid_social')
    assert.equal(r.payload.campaign, 'CAMP-42')
    assert.equal(r.payload.fullName, 'Jane Carter')
    assert.equal(r.payload.service, 'window_replacement')
    assert.equal(r.payload.state, 'GA')
    assert.equal(r.payload.facebookLeadId, 'LG-1001')
    assert.equal(r.payload.facebookFormId, 'FORM-9')
    assert.equal(r.payload.facebookAdId, 'AD-7')
    assert.equal('gclid' in r.payload, false)
  })

  test('missing city field_data yields needs_review for the Facebook lead', async () => {
    const input = facebookLead({
      field_data: (facebookLead().field_data as Array<{ name: string }>).filter(f => f.name !== 'city'),
    })
    const r = await submitLead(input)
    assert.equal(r.status, 'needs_review')
    assert.deepEqual(r.missingFields, ['city'])
    assert.equal(read('incomplete_leads.json')[0].facebookLeadId, 'LG-1001')
  })

  test('same leadgen_id again is an identical duplicate', async () => {
    await submitLead(facebookLead())
    const r = await submitLead(facebookLead())
    assert.equal(r.status, 'accepted')
    assert.equal(read('reconciliation.json').duplicateAccepted, true)
    assert.equal(read('crm_leads.json').length, 1)
  })

  test('Facebook consent must be true', async () => {
    const r = await submitLead(facebookLead({ consent: false }))
    assert.equal(r.status, 'rejected')
  })
})

describe('google_ads leads', () => {
  test('keeps gclid and landingPage on the saved record', async () => {
    const r = await submitLead(googleAds())
    assert.equal(r.status, 'accepted')
    assert.equal(r.payload.source, 'google_ads')
    assert.equal(r.payload.gclid, 'GCLID-SAMPLE-001')
    assert.equal(r.payload.landingPage, '/window-replacement?gclid=GCLID-SAMPLE-001')
  })

  test('same email with a different gclid is a separate record', async () => {
    await submitLead(googleAds())
    const r = await submitLead(googleAds({ gclid: 'GCLID-OTHER' }))
    assert.equal(r.status, 'accepted')
    assert.equal(read('crm_leads.json').length, 2)
    assert.equal(read('reconciliation.json').duplicateAccepted, false)
  })
})

describe('matchedSubmission contract', () => {
  test('identical resubmission is a no-op duplicate that leaves the CRM ledger byte-identical', async () => {
    await submitLead(complete)
    const before = raw('crm_leads.json')
    const r = await submitLead(lead({ receivedAt: '2025-01-03T12:00:00Z' }))
    assert.equal(r.status, 'accepted')
    assert.equal(raw('crm_leads.json'), before)
    const rec = read('reconciliation.json')
    assert.equal(rec.duplicateAccepted, true)
    assert.equal(rec.duplicateIncomplete, false)
  })

  test('identity matches email case-insensitively and keeps the stored audit fields', async () => {
    await submitLead(complete)
    const r = await submitLead(lead({ email: 'JANE.CARTER@EXAMPLE.COM', receivedAt: '2025-01-03T12:00:00Z' }))
    assert.equal(r.status, 'accepted')
    const crm = read('crm_leads.json')
    assert.equal(crm.length, 1)
    assert.equal(crm[0].email, 'jane.carter@example.com')
    assert.equal(crm[0].submittedAt, '2025-01-02T15:30:00Z')
    assert.equal(read('reconciliation.json').duplicateAccepted, true)
  })

  test('different campaign for the same email is a new identity, not a duplicate', async () => {
    await submitLead(complete)
    const r = await submitLead(lead({ campaign: 'other-campaign' }))
    assert.equal(r.status, 'accepted')
    assert.equal(read('crm_leads.json').length, 2)
    assert.equal(read('reconciliation.json').duplicateAccepted, false)
  })

  const contradictions: Array<[string, Record<string, unknown>]> = [
    ['city', { city: 'Dallas' }],
    ['state', { state: 'TX' }],
    ['service', { service: 'doors' }],
    ['phone', { phone: '+14045550999' }],
    ['fullName', { fullName: 'John Carter' }],
  ]

  for (const [field, override] of contradictions) {
    test(`contradictory ${field} is rejected with identity_conflict and the stored record is not mutated`, async () => {
      await submitLead(complete)
      const before = raw('crm_leads.json')
      const r = await submitLead(lead(override))
      assert.equal(r.status, 'rejected')
      assert.equal(r.reason, 'identity_conflict')
      assert.equal(raw('crm_leads.json'), before)
      assert.equal(exists('submission.json'), false)
    })
  }

  test('contradictory submission against a stored incomplete record is rejected and leaves it unchanged', async () => {
    await submitLead(withoutCity({ state: 'GA' }))
    const before = raw('incomplete_leads.json')
    const r = await submitLead(lead({ state: 'TX' }))
    assert.equal(r.status, 'rejected')
    assert.equal(r.reason, 'identity_conflict')
    assert.equal(raw('incomplete_leads.json'), before)
  })

  test('identical resubmission of an incomplete lead is a duplicateIncomplete no-op', async () => {
    await submitLead(withoutCity())
    const before = raw('incomplete_leads.json')
    const r = await submitLead(withoutCity({ receivedAt: '2025-01-03T12:00:00Z' }))
    assert.equal(r.status, 'needs_review')
    assert.deepEqual(r.missingFields, ['city'])
    assert.equal(raw('incomplete_leads.json'), before)
    assert.equal(read('reconciliation.json').duplicateIncomplete, true)
    assert.equal(read('reconciliation.json').duplicateAccepted, false)
  })
})

describe('incomplete-to-complete promotion', () => {
  test('completing submission promotes the lead, keeps first-contact submittedAt, and uses ready_for_crm', async () => {
    const first = await submitLead(withoutCity({ receivedAt: '2025-01-02T10:00:00Z' }))
    assert.equal(first.status, 'needs_review')

    const second = await submitLead(lead({ receivedAt: '2025-01-03T12:00:00Z' }))
    assert.equal(second.status, 'accepted')
    assert.equal(second.payload.status, 'ready_for_crm')
    assert.equal(second.payload.submittedAt, '2025-01-02T10:00:00Z')

    const crm = read('crm_leads.json')
    assert.equal(crm.length, 1)
    assert.equal(crm[0].status, 'ready_for_crm')
    assert.equal(crm[0].city, 'Atlanta')
    assert.equal(crm[0].submittedAt, '2025-01-02T10:00:00Z')
    assert.deepEqual(read('submission.json'), crm[0])
    assert.deepEqual(read('incomplete_leads.json'), [])

    const rec = read('reconciliation.json')
    assert.equal(rec.promotedIncomplete.length, 1)
    assert.equal(rec.promotedIncomplete[0].status, 'promoted_to_crm')
    assert.equal(rec.promotedIncomplete[0].submittedAt, '2025-01-02T10:00:00Z')
    assert.equal(rec.duplicateAccepted, false)
    assert.equal(rec.duplicateIncomplete, false)
  })

  test('a promoted lead appears once in lead_sources, in its CRM group, as ready_for_crm', async () => {
    await submitLead(withoutCity())
    await submitLead(lead())
    const sources = read('lead_sources.json')
    assert.equal(sources.website.length, 1)
    assert.equal(sources.website[0].status, 'ready_for_crm')
  })

  test('partial completion stays needs_review with updated missingFields and first-contact time', async () => {
    const { state: _state, ...noCityNoState } = withoutCity({ receivedAt: '2025-01-02T10:00:00Z' })
    const first = await submitLead(noCityNoState)
    assert.equal(first.status, 'needs_review')
    assert.deepEqual(first.missingFields, ['city', 'state'])

    const second = await submitLead({ ...complete, city: 'Atlanta', state: undefined, receivedAt: '2025-01-03T12:00:00Z' })
    assert.equal(second.status, 'needs_review')
    assert.deepEqual(second.missingFields, ['state'])
    const [entry] = read('incomplete_leads.json')
    assert.equal(entry.city, 'Atlanta')
    assert.equal(entry.submittedAt, '2025-01-02T10:00:00Z')
    assert.deepEqual(entry.missingFields, ['state'])
    assert.equal(read('reconciliation.json').promotedIncomplete.length, 0)
  })
})

describe('batch submission (array input)', () => {
  test('incomplete then completing record in one batch promotes within the same submission', async () => {
    const r = await submitLead([
      withoutCity({ receivedAt: '2025-01-02T10:00:00Z' }),
      lead({ receivedAt: '2025-01-03T12:00:00Z' }),
    ])
    assert.equal(r.status, 'accepted')
    const crm = read('crm_leads.json')
    assert.equal(crm.length, 1)
    assert.equal(crm[0].submittedAt, '2025-01-02T10:00:00Z')
    assert.deepEqual(read('submission.json'), crm[0])
    assert.equal(read('reconciliation.json').promotedIncomplete.length, 1)
    assert.deepEqual(read('incomplete_leads.json'), [])
  })

  test('submission.json reflects the most recently accepted record, not a later needs_review one', async () => {
    const accepted = lead({ email: 'first@example.com' })
    const r = await submitLead([accepted, withoutCity({ email: 'second@example.com' })])
    assert.equal(r.status, 'accepted')
    assert.equal(read('submission.json').email, 'first@example.com')
    assert.equal(read('incomplete_leads.json').length, 1)
  })

  test('a batch with no accepted record writes no submission.json and removes a stale one', async () => {
    seed('submission.json', { stale: true })
    const r = await submitLead([withoutCity(), withoutCity({ email: 'second@example.com' })])
    assert.equal(r.status, 'needs_review')
    assert.equal(exists('submission.json'), false)
  })

  test('duplicates inside one batch set duplicateAccepted in reconciliation', async () => {
    const r = await submitLead([complete, complete])
    assert.equal(r.status, 'accepted')
    assert.equal(read('crm_leads.json').length, 1)
    assert.equal(read('reconciliation.json').duplicateAccepted, true)
  })

  test('duplicate incomplete records inside one batch set duplicateIncomplete', async () => {
    const r = await submitLead([withoutCity(), withoutCity()])
    assert.equal(r.status, 'needs_review')
    assert.equal(read('reconciliation.json').duplicateIncomplete, true)
    assert.equal(read('reconciliation.json').duplicateAccepted, false)
  })

  test('one rejected record rejects the whole batch: no ledger changes and stale submission removed', async () => {
    seed('submission.json', { stale: true })
    const r = await submitLead([lead({ email: 'new@example.com' }), lead({ email: 'bad-email' })])
    assert.equal(r.status, 'rejected')
    assert.equal(exists('crm_leads.json'), false)
    assert.equal(exists('incomplete_leads.json'), false)
    assert.equal(exists('reconciliation.json'), false)
    assert.equal(exists('submission.json'), false)
  })

  test('a contradictory record anywhere in the batch rejects the entire batch', async () => {
    await submitLead(complete)
    const before = snapshot()
    const r = await submitLead([lead({ email: 'new@example.com' }), lead({ city: 'Dallas' })])
    assert.equal(r.status, 'rejected')
    assert.equal(r.reason, 'identity_conflict')
    assert.deepEqual(snapshot(), before)
  })

  test('an empty array is rejected without crashing', async () => {
    const r = await submitLead([])
    assert.equal(r.status, 'rejected')
  })
})

describe('lead_sources derived view and source grouping', () => {
  test('always has website, google_ads, and facebook_lead_ads groups, even when empty', async () => {
    await submitLead(complete)
    const sources = read('lead_sources.json')
    assert.deepEqual(sources.google_ads, [])
    assert.deepEqual(sources.facebook_lead_ads, [])
    assert.equal(sources.website.length, 1)
  })

  test('groups saved entries by source and each entry equals the saved ledger object', async () => {
    await submitLead(complete)
    await submitLead(googleAds())
    const crm = read('crm_leads.json')
    const sources = read('lead_sources.json')
    assert.deepEqual(sources.website, [crm.find((r: any) => r.source === 'website')])
    assert.deepEqual(sources.google_ads, [crm.find((r: any) => r.source === 'google_ads')])
  })

  test('custom sources keep their exact value as an extra key after the always-present groups', async () => {
    await submitLead(lead({ source: 'Partner Referral' }))
    const sources = read('lead_sources.json')
    assert.equal(sources['Partner Referral'].length, 1)
    const keys = Object.keys(sources)
    assert.deepEqual(keys.slice(0, 3), ['website', 'google_ads', 'facebook_lead_ads'])
    assert.ok(keys.indexOf('Partner Referral') > 2)
  })

  test('incomplete entries follow CRM entries within their source group', async () => {
    await submitLead(complete)
    await submitLead(withoutCity({ email: 'second@example.com' }))
    const sources = read('lead_sources.json')
    assert.equal(sources.website.length, 2)
    assert.equal(sources.website[0].email, 'jane.carter@example.com')
    assert.equal(sources.website[1].email, 'second@example.com')
    assert.equal(sources.website[1].status, 'needs_review')
  })

  test('lead_sources equals the projection of crm_leads.json followed by incomplete_leads.json', async () => {
    await submitLead(complete)
    await submitLead(googleAds())
    await submitLead(withoutCity({ email: 'second@example.com' }))
    await submitLead(facebookLead())
    const crm = read('crm_leads.json')
    const incomplete = read('incomplete_leads.json')
    const expected: Record<string, unknown[]> = { website: [], google_ads: [], facebook_lead_ads: [] }
    for (const entry of [...crm, ...incomplete]) {
      expected[entry.source] ??= []
      expected[entry.source].push(entry)
    }
    assert.deepEqual(read('lead_sources.json'), expected)
  })

  test('an inconsistent but well-formed lead_sources.json is repaired and not quarantined', async () => {
    seed('lead_sources.json', { website: [], google_ads: [], facebook_lead_ads: [] })
    await submitLead(complete)
    assert.equal(read('lead_sources.json').website.length, 1)
    assert.equal(readRejected().some(r => r.path.endsWith('lead_sources.json')), false)
  })
})

describe('malformed ledger recovery', () => {
  test('malformed crm_leads.json (invalid JSON) is quarantined and recorded with reason invalid_json', async () => {
    const broken = '{"broken": '
    seed('crm_leads.json', broken)
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')

    const expected = { path: file('crm_leads.json'), reason: 'invalid_json' }
    assert.deepEqual(readRejected(), [expected])
    assert.deepEqual(read('reconciliation.json').quarantinedLedgers, [expected])
    assert.ok(path.isAbsolute(readRejected()[0].path))

    const copies = fs.readdirSync(path.join(OUT, 'quarantine')).filter(n => /^crm_leads\..+\.json$/.test(n))
    assert.equal(copies.length, 1)
    assert.equal(fs.readFileSync(path.join(OUT, 'quarantine', copies[0]), 'utf8'), broken)
  })

  test('malformed crm_leads.json (wrong shape) is recorded with reason invalid_shape', async () => {
    seed('crm_leads.json', { not: 'an array' })
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.equal(readRejected()[0].reason, 'invalid_shape')
  })

  test('crm_leads.json with a malformed entry is treated as invalid_shape', async () => {
    seed('crm_leads.json', [{ email: 'x@example.com' }])
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.equal(readRejected()[0].reason, 'invalid_shape')
  })

  test('malformed incomplete_leads.json is recorded and the run continues', async () => {
    seed('incomplete_leads.json', '[oops')
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.deepEqual(readRejected(), [{ path: file('incomplete_leads.json'), reason: 'invalid_json' }])
  })

  test('malformed lead_sources.json is recorded in rejected_ledgers.json and rebuilt', async () => {
    seed('lead_sources.json', '{')
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.deepEqual(readRejected(), [{ path: file('lead_sources.json'), reason: 'invalid_json' }])
    assert.equal(read('lead_sources.json').website.length, 1)
  })

  test('a malformed rejected_ledgers.json is replaced by a valid array', async () => {
    seed('rejected_ledgers.json', '{nope')
    const r = await submitLead(complete)
    assert.equal(r.status, 'accepted')
    assert.ok(Array.isArray(read('rejected_ledgers.json')))
  })

  test('rejected_ledgers.json accumulates without duplicating a recorded ledger', async () => {
    seed('crm_leads.json', '{bad')
    await submitLead(complete)
    await submitLead(lead({ email: 'second@example.com' }))
    assert.equal(readRejected().length, 1)
  })

  test('a rejected lead does not repair a malformed ledger; its bytes stay unchanged', async () => {
    seed('crm_leads.json', '{bad')
    const r = await submitLead(lead({ email: 'bad-email' }))
    assert.equal(r.status, 'rejected')
    assert.equal(raw('crm_leads.json'), '{bad')
  })
})

describe('atomic multi-file commit', () => {
  // Spec-mandated: a target that cannot be written must not change any existing ledger.
  test('if a target output cannot be written, rejects and changes no existing ledger', async () => {
    await submitLead(complete)
    const before = snapshot()
    fs.rmSync(file('reconciliation.json'))
    fs.mkdirSync(file('reconciliation.json'))
    const r = await submitLead(lead({ email: 'second@example.com' }))
    assert.equal(r.status, 'rejected')
    assert.equal(raw('crm_leads.json'), before['crm_leads.json'])
    assert.equal(raw('incomplete_leads.json'), before['incomplete_leads.json'])
    assert.equal(raw('lead_sources.json'), before['lead_sources.json'])
  })

  // Stricter than the spec text: the spec requires ledgers to stay unchanged on a commit failure and
  // removes stale submission.json for invalid leads. This checks that the prior run's submission.json
  // is not left in place as if it were still the current accepted result.
  test('stricter expectation: a failed commit does not leave the prior run submission.json behind', async () => {
    await submitLead(complete)
    fs.rmSync(file('reconciliation.json'))
    fs.mkdirSync(file('reconciliation.json'))
    const r = await submitLead(lead({ email: 'second@example.com' }))
    assert.equal(r.status, 'rejected')
    assert.equal(exists('submission.json'), false)
  })
})

describe('shared pipeline wiring', () => {
  test('CLI and React form both import submitLead from ../lib/submitLead.ts and no direct writers', () => {
    const cli = fs.readFileSync(path.join(APP, 'src/scripts/submit.ts'), 'utf8')
    const form = fs.readFileSync(path.join(APP, 'src/components/LeadForm.tsx'), 'utf8')
    assert.match(cli, /from ['"]\.\.\/lib\/submitLead\.ts['"]/)
    assert.match(form, /from ['"]\.\.\/lib\/submitLead\.ts['"]/)
    assert.doesNotMatch(cli, /outputStore|writeFileSync/)
    assert.doesNotMatch(form, /outputStore|writeFileSync|node:fs/)
  })
})

describe('npm run submit CLI', () => {
  let originalInput: Buffer

  before(() => {
    originalInput = fs.readFileSync(INPUT_FILE)
  })

  after(() => {
    fs.writeFileSync(INPUT_FILE, originalInput)
  })

  function runSubmit(input: unknown) {
    fs.writeFileSync(INPUT_FILE, `${JSON.stringify(input, null, 2)}\n`)
    return spawnSync('npm', ['run', 'submit'], { cwd: APP, encoding: 'utf8', timeout: 120_000 })
  }

  test('accepted lead exits 0 and writes the accepted outputs', () => {
    const r = runSubmit(complete)
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`)
    assert.ok(exists('submission.json'))
    assert.ok(exists('crm_leads.json'))
  })

  test('needs_review lead exits 0 and writes no submission.json', () => {
    const r = runSubmit(withoutCity())
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`)
    assert.equal(exists('submission.json'), false)
    assert.ok(exists('incomplete_leads.json'))
  })

  test('rejected lead exits nonzero and removes a stale submission.json', () => {
    seed('submission.json', { stale: true })
    const r = runSubmit(lead({ consent: false }))
    assert.notEqual(r.status, 0)
    assert.equal(exists('submission.json'), false)
  })

  test('array input runs as one batch and exits 0', () => {
    const r = runSubmit([complete, lead({ email: 'second@example.com' })])
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`)
    assert.equal(read('crm_leads.json').length, 2)
  })

  test('batch containing a rejected record exits nonzero and changes no ledger', () => {
    const r = runSubmit([complete, lead({ email: 'bad-email' })])
    assert.notEqual(r.status, 0)
    assert.equal(exists('crm_leads.json'), false)
  })

  test('failed output commit exits nonzero', () => {
    fs.mkdirSync(file('reconciliation.json'))
    const r = runSubmit(complete)
    assert.notEqual(r.status, 0, `${r.stdout}\n${r.stderr}`)
    assert.equal(exists('crm_leads.json'), false)
  })
})

describe('npm run build and npm test', () => {
  test('production build exits 0', () => {
    const r = spawnSync('npm', ['run', 'build'], { cwd: APP, encoding: 'utf8', timeout: 170_000 })
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`)
  })

  test('npm test exits 0', () => {
    const r = spawnSync('npm', ['test'], { cwd: APP, encoding: 'utf8', timeout: 170_000 })
    assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`)
  })
})
