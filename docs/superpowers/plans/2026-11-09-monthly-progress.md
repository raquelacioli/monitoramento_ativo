# Monthly Firestore implementation record

## Status

Native monthly persistence implemented; all original public functions and dataclasses retained (AST comparison). No SQLite imports, SQL execution, database files, commits or remote production operations. Test fixtures now use isolated emulator namespaces.

Emulator verification: `python -B -m unittest discover -s tests -p test_firestore_monthly.py -q`: 10/10 passing; `test_monthly_store.py`: 10/10 passing, existing assertions and scenarios preserved. Integration covers 1,000 records, interrupted staged import, idempotent resume, publication visibility, pending-operation locks, revisions, response audit, dashboards and unit isolation.

Additional review tests reproduced two failures (RED): concurrent identical imports both reported the inserted count, and a manual thread accepted a blank actor. Publication now returns a duplicate outcome to the losing caller (stored data were already unique), and mutation entry points require a nonblank actor. GREEN confirmed both fixes. Other concurrency tests verify eight simultaneous draft patches retain every field and monotonically increasing versions; fingerprint mismatch cannot resume an interrupted import; a disconnected response after successful publication can be retried idempotently.

## Import protocol

All mutations use Store.run guard `monthly`. Normal mutations check `monthly_control/key('import')` for pending operation. An import reserves a stable import_id and content fingerprint, writes bounded batches (80 records; maximum 160 record/revision writes plus coverage and metadata), then publishes its metadata and competence change together. New records and history remain invisible until monthly_imports.published. Conflicts never overwrite existing records or their unit updates. Failure leaves old competence and published rows visible; resend identical parsed records/source/coverage to resume. A different import or mutation is blocked until completion. This intentionally serializes monthly writes while an import is incomplete.

## Legacy migration mapping

Every key below uses `monitoramento.firestore_store.key`; all collections are below the Store namespace.

- monthly_competences: key(agravo, competence), preserve all columns.
- monthly_imports: key(id); preserve original id and columns; add published=True, inserted=record_count, conflicts=actual count, next_batch=0, fingerprint='legacy'. No `import_id` field on this document.
- monthly_import_keys: key(agravo, competence, source_sha256), value {import_id: original_id}.
- monthly_import_unit_coverage: key(import_id, unit_ref), preserve import_id/unit_ref and denormalize agravo/competence from monthly_imports.
- monthly_records: key(agravo, patient_ref, competence), original_values/updated_values parsed JSON maps. Preserve import_id and other columns, default reviewer_note=''.
- monthly_record_revisions: key(agravo, patient_ref, competence, version), parse original_values/updated_values; denormalize import_id from matching monthly_records so unpublished imports remain hidden. Preserve action/actor/occurred_at/state/note. Fields unit_ref/updated_by/updated_at can be copied from matching record; reading revision API only requires original columns.
- monthly_import_conflicts: key(import_id, agravo, patient_ref, competence), parse stored_original_values/incoming_original_values.
- monthly_vigilance_notes: key(original_id) or any unique key; add version from corresponding record revision (matching agravo/patient_ref/competence, action, occurred_at), fallback ascending original_id. Existing API orders by version.
- monthly_followups: key(id), preserve columns; denormalize latest submitted response as response_text/response_by/response_at/response_version; latest draft newer than submission as draft_text; latest_response_version=max(all response versions, default 0); last_operation_at=max(updated_at, all event and response occurred_at). Defaults empty text, None response_by/response_at, 0 versions.
- monthly_followup_responses: key(id), preserve all columns, including id.
- monthly_followup_events: key(id), preserve all columns, including id.
- monthly_monitoring_deadlines: key(agravo, competence), preserve columns.
- monthly_monitoring_deadline_events: key(id), parse old_values/new_values JSON.
- monthly_unit_confirmations: key(agravo, competence, unit_ref), preserve columns.
- monthly_unit_confirmation_events: key(id), preserve columns, including id.

Counter documents use Store._counters/key(collection_name), data {value: max_legacy_id}. Required monthly counters: monthly_imports, monthly_followups, monthly_followup_events, monthly_followup_responses, monthly_monitoring_deadline_events, monthly_unit_confirmation_events. Other migrated numeric ids need no counters because new records use composite/version keys.

Do not migrate SQLite schema/indices into Firestore. Do not migrate monthly_control pending state for a complete legacy database; absent control means no import pending. Import ordering/deduplication requires monthly_import_keys to be present.

## Decisions

- Read after staged writes is provided by Store UnitOfWork; no SQL compatibility adapter.
- Document history uses native maps instead of JSON strings; public API outputs remain dicts.
- Existing SQL-only tests changed to equivalent direct Firestore inspection for closed_by; no assertions removed.
- Credentials and real SQLite were not read by this subtask.
