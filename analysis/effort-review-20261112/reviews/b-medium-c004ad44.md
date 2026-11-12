```json
{
  "findings": [
    {
      "location": "src/lib/submitLead.ts, submitLead() change-set construction (`if (accepted || crmChanged || ...)` and `if (!accepted || incompleteChanged || ...)`)",
      "requirement": "matchedSubmission.identicalDuplicate: an identical duplicate is \"a no-op that does not rewrite existing ledgers\". Only the reconciliation duplicate flags should change.",
      "reproduction": "With crm_leads.json already containing the lead from src/data/lead_input.json (the Jane Carter google_ads record), run `npm run submit` again with the same input. The CRM branch matches via identityKey, classifyMatch returns 'identical', and the function returns accepted(state.crm[i]). Because `accepted` is true, the `accepted || crmChanged` condition pushes crm_leads.json into the commit even though its content did not change.",
      "actual": "crm_leads.json is rewritten on every identical duplicate (accepted path). For an identical duplicate of a stored incomplete lead (needs_review path), incomplete_leads.json is rewritten by `!accepted`. The ledger write happens even when nothing changed, so a hand-formatted ledger is reformatted and its mtime changes.",
      "expected": "A duplicate no-op leaves crm_leads.json and incomplete_leads.json untouched. Only submission.json, lead_sources.json, and reconciliation.json (with duplicateAccepted/duplicateIncomplete set) are updated.",
      "confidence": "medium"
    }
  ],
  "suspicions": [
    "src/lib/ledger.ts loadLedgerState(): a malformed crm_leads.json or incomplete_leads.json is quarantined but then treated as [] and rewritten as [] by submitLead's commit. Any recoverable accepted records in the malformed file are discarded rather than preserved. The spec says to 'recover safely' and record the ledger, so this may be acceptable, but it can break the 'immutable audit records' expectation. Not verified against the hidden tests.",
    "src/lib/submitLead.ts rejectLead(): a rejected lead does not record a malformed ledger in rejected_ledgers.json, even though loadLedgerState found one. The spec's rejected_ledgers requirement may expect quarantine to be recorded on every run that detects a malformed ledger. Ambiguous.",
    "src/lib/validation.ts normalizeLead(): customer-entered text (fullName, city, email) is trimmed before saving. fieldPreservation.preserveCustomerEnteredText may require the text to be stored as entered, with trimming used only for matching. Low confidence.",
    "src/lib/identity.ts comparable(): fullName and city are compared case-insensitively with whitespace collapsed. The spec only says to compare 'normalized values', so whether this counts as normalization for contradiction checks is ambiguous. A stored 'Jane Carter' versus incoming 'jane carter' is treated as identical rather than contradictory.",
    "src/lib/submitLead.ts applyRecord(), incomplete promotion path: the completing submission's attribution keys (for example gclid or facebookFormId) are never merged into the stored record. The promotion contract only covers profile fields, so this may be intended.",
    "src/lib/validation.ts normalizeLead(): Facebook leadgen_id and campaign_id are passed through textOf(), which rejects non-string JSON values (numbers). A webhook that sends numeric IDs would be rejected as invalid_lead. The spec does not say whether numeric IDs are allowed.",
    "src/lib/ledger.ts isEntry(): crm_leads.json and incomplete_leads.json entries are accepted as valid even when required CRM fields are empty strings (for example phone: ''). An accepted-status entry with a blank required field is therefore not flagged as malformed. Possibly 'inconsistent' rather than 'malformed', so it may not need quarantine.",
    "src/components/LeadForm.tsx TRACKING constant: every form submission is hard-coded to source google_ads, campaign spring-window-leads, utmMedium cpc. The spec does not define how the form should set tracking values, so this may be a deliberate choice or may be incorrect.",
    "src/lib/outputStore.ts createOutputStore() browser branch: the browser store is empty and commits are no-ops, so the React form cannot detect duplicates or promotions across submissions. The spec requires the same pipeline entry point, which is met, but the form's accepted result is not persisted anywhere. Intended per the code comment, but worth confirming.",
    "Not verified: I did not run `npm test`, `npm run build`, or `npm run submit`, and I did not check tsconfig.json or vite.config.ts. Build and test behavior, JSON import support, and the browser bundle's handling of the dynamic node:fs import are all unconfirmed."
  ]
}
```