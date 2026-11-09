"""Explicit, resumable migration. Source is always opened read-only.

Never called by the web application, build or startup command.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from monitoramento.firestore_store import get_store, key

TABLES = (
    'auth_users', 'auth_sessions', 'auth_login_attempts', 'auth_password_reset_tokens',
    'auth_password_reset_limits', 'tracking_updates', 'monthly_competences', 'monthly_imports',
    'monthly_import_unit_coverage', 'monthly_records', 'monthly_record_revisions',
    'monthly_import_conflicts', 'monthly_vigilance_notes', 'monthly_followups',
    'monthly_followup_responses', 'monthly_followup_events', 'monthly_monitoring_deadlines',
    'monthly_monitoring_deadline_events', 'monthly_unit_confirmations',
    'monthly_unit_confirmation_events',
)
EXCLUDED = {'auth_sessions', 'auth_login_attempts', 'auth_password_reset_tokens',
            'auth_password_reset_limits'}
COMPOSITE = {
    'tracking_updates': ('agravo', 'record_id'),
    'monthly_competences': ('agravo', 'competence'),
    'monthly_import_unit_coverage': ('import_id', 'unit_ref'),
    'monthly_records': ('agravo', 'patient_ref', 'competence'),
    'monthly_record_revisions': ('agravo', 'patient_ref', 'competence', 'version'),
    'monthly_import_conflicts': ('import_id', 'agravo', 'patient_ref', 'competence'),
    'monthly_monitoring_deadlines': ('agravo', 'competence'),
    'monthly_unit_confirmations': ('agravo', 'competence', 'unit_ref'),
}
JSON_FIELDS = {'original_values', 'updated_values', 'stored_original_values',
               'incoming_original_values', 'old_values', 'new_values', 'form_values'}
REQUIRED = {
    'auth_users': 'id username password_hash password_salt role unit active must_change_password created_at',
    'tracking_updates': 'agravo record_id followup_status contacts_registered contacts_examined pending_items observation last_updated',
    'monthly_competences': 'agravo competence state opened_by opened_at closed_at',
    'monthly_imports': 'id agravo competence source_sha256 imported_by imported_at record_count',
    'monthly_import_unit_coverage': 'import_id unit_ref',
    'monthly_records': 'agravo patient_ref competence unit_ref import_id original_values updated_values state version updated_by updated_at reviewer_note',
    'monthly_record_revisions': 'id agravo patient_ref competence version action actor occurred_at original_values updated_values state note',
    'monthly_import_conflicts': 'id import_id agravo patient_ref competence stored_original_values incoming_original_values detected_at',
    'monthly_vigilance_notes': 'id agravo patient_ref competence actor occurred_at action note',
    'monthly_followups': 'id agravo patient_ref unit_ref competence rule_id automatic_text vigilance_text state priority created_by created_at updated_by updated_at',
    'monthly_followup_responses': 'id followup_id version actor occurred_at state response_text',
    'monthly_followup_events': 'id followup_id actor occurred_at action old_state new_state old_text new_text priority',
    'monthly_monitoring_deadlines': 'agravo competence opened_on due_on extension_due_on updated_by updated_at',
    'monthly_monitoring_deadline_events': 'id agravo competence actor occurred_at action old_values new_values',
    'monthly_unit_confirmations': 'agravo competence unit_ref status note updated_by updated_role updated_at',
    'monthly_unit_confirmation_events': 'id agravo competence unit_ref actor actor_role occurred_at action old_status new_status note',
}


def _validate(tables):
    if not any(rows for name, rows in tables.items() if name not in EXCLUDED):
        raise ValueError('A origem não contém dados reconhecidos para migrar.')
    for name, rows in tables.items():
        if name in EXCLUDED: continue
        required = set(REQUIRED[name].split())
        for row in rows:
            if not required <= row.keys(): raise ValueError('Colunas obrigatórias ausentes no SQLite.')
            for field in ('id', 'import_id', 'followup_id', 'version'):
                if field in row and (type(row[field]) is not int or row[field] < 1):
                    raise ValueError('Identificador ou versão inválida na origem.')
            if 'agravo' in row and row['agravo'] not in ('tuberculose', 'hanseniase'):
                raise ValueError('Agravo inválido na origem.')
            if name == 'auth_users':
                from monitoramento.auth import _validate_account, _normalize_email
                if (not isinstance(row['username'], str) or not isinstance(row['role'], str)
                        or type(row['created_at']) is not int):
                    raise ValueError('Conta inválida na origem.')
                _validate_account(row['username'], row['role'], row['unit'])
                _normalize_email(row.get('email'))
                if (not isinstance(row['password_hash'], bytes) or len(row['password_hash']) != 32
                        or not isinstance(row['password_salt'], bytes) or len(row['password_salt']) != 16
                        or row['active'] not in (0, 1) or row['must_change_password'] not in (0, 1)):
                    raise ValueError('Hash, salt ou estado de conta inválido na origem.')


def _read_source(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('A integridade do SQLite não foi confirmada.')
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables - set(TABLES) - {'sqlite_sequence'}:
            raise ValueError('SQLite contém tabelas desconhecidas; revise o esquema antes de migrar.')
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite contém referências inválidas.')
        for name in tables & REQUIRED.keys():
            columns = {r['name'] for r in connection.execute(f'PRAGMA table_info({name})')}
            if not set(REQUIRED[name].split()) <= columns:
                raise ValueError('Esquema SQLite incompatível: faltam colunas obrigatórias.')
        result = {name: [dict(r) for r in connection.execute(f'SELECT * FROM {name}')]
                  if name in tables else [] for name in TABLES}
    return result


def _identity(row):
    return tuple(row[k] for k in ('agravo', 'patient_ref', 'competence'))


def _prepare(tables):
    _validate(tables)
    docs = []
    imports = {r['id']: r for r in tables['monthly_imports']}
    periods = {(r['agravo'], r['competence']) for r in tables['monthly_competences']}
    records = {_identity(r): r for r in tables['monthly_records']}
    followups = {r['id']: r for r in tables['monthly_followups']}
    usernames, emails = set(), set()
    for name, rows in tables.items():
        if name in EXCLUDED: continue
        for original in rows:
            row = dict(original)
            for field in JSON_FIELDS & row.keys():
                if isinstance(row[field], str):
                    try: row[field] = json.loads(row[field])
                    except (ValueError, TypeError):
                        raise ValueError('Campo JSON inválido no SQLite.') from None
                if not isinstance(row[field], dict): raise ValueError('Mapa JSON inválido no SQLite.')
            if 'import_id' in row and row['import_id'] not in imports:
                raise ValueError('Referência de importação inexistente.')
            if name == 'monthly_records' and (row['agravo'], row['competence']) not in periods:
                raise ValueError('Referência de competência inexistente.')
            if name in ('monthly_followups', 'monthly_record_revisions', 'monthly_vigilance_notes'):
                if _identity(row) not in records: raise ValueError('Referência de ficha inexistente.')
            if 'followup_id' in row and row['followup_id'] not in followups:
                raise ValueError('Referência de solicitação inexistente.')
            if name == 'auth_users':
                row.setdefault('email', None)
                row['username'] = row['username'].strip().casefold()
                if row['username'] in usernames: raise ValueError('Usuários duplicados na origem.')
                usernames.add(row['username'])
                row['email'] = row['email'].strip().casefold() if row['email'] else None
                if row['email'] and row['email'] in emails: raise ValueError('E-mails duplicados na origem.')
                if row['email']: emails.add(row['email'])
                row['active'] = bool(row.get('active', True))
                row['must_change_password'] = bool(row.get('must_change_password', True))
                row.update(session_version=1, reset_version=1)
                docs.append(('auth_names', key(row['username']), {'user_id': row['id']}))
                if row['email']: docs.append(('auth_emails', key(row['email']), {'user_id': row['id']}))
            if name == 'monthly_imports':
                conflicts = sum(r['import_id'] == row['id'] for r in tables['monthly_import_conflicts'])
                row.update(published=True, inserted=row['record_count'], conflicts=conflicts,
                           next_batch=0, fingerprint='legacy')
                docs.append(('monthly_import_keys', key(row['agravo'], row['competence'], row['source_sha256']),
                             {'import_id': row['id']}))
            if name == 'monthly_import_unit_coverage':
                imported = imports[row['import_id']]
                row.update(agravo=imported['agravo'], competence=imported['competence'])
            if name == 'monthly_records': row.setdefault('reviewer_note', '')
            if name == 'tracking_updates': row.setdefault('form_values', {})
            if name == 'monthly_competences': row.setdefault('closed_by', None)
            if name == 'monthly_record_revisions':
                row['import_id'] = records[_identity(row)]['import_id']
            if name == 'monthly_vigilance_notes':
                revisions = [r for r in tables['monthly_record_revisions']
                             if _identity(r) == _identity(row) and r['occurred_at'] == row['occurred_at']]
                row['version'] = max((r['version'] for r in revisions), default=row['id'])
            if name == 'monthly_followups':
                responses = sorted((r for r in tables['monthly_followup_responses']
                                    if r['followup_id'] == row['id']), key=lambda r: r['version'])
                submitted = [r for r in responses if r['state'] == 'submitted']
                last = submitted[-1] if submitted else None
                draft = responses[-1] if responses and responses[-1]['state'] == 'draft' else None
                row.update(response_text=last['response_text'] if last else '',
                           response_by=last['actor'] if last else None,
                           response_at=last['occurred_at'] if last else None,
                           response_version=last['version'] if last else 0,
                           draft_text=draft['response_text'] if draft else '',
                           latest_response_version=max((r['version'] for r in responses), default=0))
                row.setdefault('field_key', 'contatos_examinados' if row['rule_id'] == 'contacts_not_examined' else '')
                times = [row['updated_at']] + [r['occurred_at'] for r in responses]
                times += [r['occurred_at'] for r in tables['monthly_followup_events'] if r['followup_id'] == row['id']]
                row['last_operation_at'] = max(times)
            fields = COMPOSITE.get(name, ('id',))
            try: identity = key(*(row[f] for f in fields))
            except KeyError: raise ValueError('Esquema SQLite incompatível com a migração.') from None
            docs.append((name, identity, row))
        if rows and 'id' in rows[0] and name not in EXCLUDED:
            docs.append(('_counters', key(name), {'value': max(r['id'] for r in rows)}))
    # Legacy upgrades inferred coverage for existing records; preserve that behavior.
    coverage = {(r['import_id'], r['unit_ref']) for r in tables['monthly_import_unit_coverage']}
    for row in tables['monthly_records']:
        pair = row['import_id'], row['unit_ref']
        if pair not in coverage:
            coverage.add(pair)
            docs.append(('monthly_import_unit_coverage', key(*pair), dict(import_id=pair[0], unit_ref=pair[1],
                        agravo=row['agravo'], competence=row['competence'])))
    identities = [(c, k) for c, k, _ in docs]
    if len(set(identities)) != len(identities): raise ValueError('Chaves duplicadas na origem.')
    return docs


def migrate(source, *, apply=False):
    tables = _read_source(source)
    docs = _prepare(tables)
    digest = hashlib.sha256(json.dumps(docs, sort_keys=True, default=lambda b: bytes(b).hex(),
                                      ensure_ascii=False).encode()).hexdigest()
    counts = {name: len(rows) for name, rows in tables.items() if rows}
    report = {'status': 'dry-run', 'counts': counts,
              'invalidated_sessions': len(tables['auth_sessions']),
              'invalidated_reset_tokens': len(tables['auth_password_reset_tokens'])}
    if not apply: return report
    store = get_store()
    if not (store.namespace.startswith('test_') or store.namespace.startswith('monitoramento_ativo_migration_')):
        raise ValueError('Migração exige namespace de preparação monitoramento_ativo_migration_<identificador>.')
    def begin(tx):
        state = tx.get('_migration', key('state'))
        if state:
            if state['source_hash'] != digest: raise ValueError('Namespace reservado para outra origem.')
            return state
        # Check every existing subcollection, not just the ones in this version.
        root = store.client.collection('monitoramento_ativo').document(store.namespace)
        if any(next(col.limit(1).stream(), None) is not None for col in root.collections()
               if col.id not in ('_guards',)):
            raise ValueError('Destino não está vazio; migração recusada.')
        state = dict(status='loading', source_hash=digest, offset=0, total=len(docs))
        tx.set('_migration', key('state'), state)
        return state
    state = store.run(begin, guard='migration')
    if state['status'] == 'complete': return {**report, 'status': 'complete'}
    for offset in range(state['offset'], len(docs), 100):
        batch = docs[offset:offset + 100]
        def copy_batch(tx):
            current = tx.get('_migration', key('state'))
            if current['offset'] > offset: return
            if current['offset'] != offset: raise ValueError('Checkpoint de migração inválido.')
            for collection, identity, data in batch: tx.set(collection, identity, data)
            tx.set('_migration', key('state'), {**current, 'offset': offset + len(batch)})
        store.run(copy_batch, guard='migration')
    # Verify every prepared document before making the namespace available.
    for collection, identity, data in docs:
        if store._get_unchecked(collection, identity) != data:
            raise ValueError('Reconciliação falhou; namespace permanece bloqueado.')
    def finish(tx):
        current = tx.get('_migration', key('state'))
        if current['offset'] != len(docs): raise ValueError('Migração incompleta.')
        tx.set('_migration', key('state'), {**current, 'status': 'complete', 'counts': counts})
    store.run(finish, guard='migration')
    return {**report, 'status': 'complete'}


def main():
    parser = argparse.ArgumentParser(description='Migração SQLite read-only para namespace Firestore de preparação.')
    parser.add_argument('--source', required=True)
    parser.add_argument('--apply', action='store_true', help='Escrever no destino; padrão somente dry-run.')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source, apply=args.apply), ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error):
        raise SystemExit('Migração recusada ou incompleta. Confira esquema, destino e credenciais; nenhum segredo é registrado.') from None


if __name__ == '__main__': main()
