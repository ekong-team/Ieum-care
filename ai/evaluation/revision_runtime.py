"""SQLite-backed, bounded revision loop. Single-process development integration."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from ai.evaluation.revision_v2 import PROMPT, apply_revision, canonical, evaluate, fingerprint, validate_context, validate_plan, verify_evaluation


class RevisionRuntime:
    def __init__(self, database):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (run_id TEXT, seq INTEGER, payload TEXT, PRIMARY KEY(run_id,seq))')
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, run_id):
        row = self.db.execute('SELECT state FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def events(self, run_id):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM events WHERE run_id=? ORDER BY seq', (run_id,))]

    def _save(self, state, event):
        event = dict(event, timestamp=datetime.now(timezone.utc).isoformat(), status=state['status'],
                     plan_version=state['current_plan']['version'], attempt=state['attempt_count'])
        with self.db:
            self.db.execute('UPDATE runs SET state=? WHERE run_id=?', (canonical(state), state['run_id']))
            seq = self.db.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (state['run_id'],)).fetchone()[0]
            self.db.execute('INSERT INTO events VALUES (?,?,?)', (state['run_id'], seq, canonical(event)))

    def run(self, run_id, plan, context, generator=None, *, max_attempts=2, evaluation=None):
        if not isinstance(run_id, str) or not run_id or len(run_id) > 150:
            raise ValueError('invalid run ID')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError('invalid attempt limit')
        validate_plan(plan)
        validate_context(context)
        initial = evaluate(plan, context)
        if evaluation is not None:
            verify_evaluation(plan, context, evaluation)
            # This baseline runtime never trusts externally supplied issue decisions.
            if fingerprint(evaluation) != fingerprint(initial):
                raise ValueError('external evaluation requires verified evaluator adapter')
        identity = fingerprint(dict(plan=plan, context=context, max_attempts=max_attempts,
                                    generator=getattr(generator, 'identity', 'not_configured')))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT input_hash,state FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if row:
                if row[0] != identity:
                    raise ValueError('run_id input conflict')
                state = json.loads(row[1])
                self.db.commit()
                # Never repeat a possibly billed call after interruption.
                if state['status'] == 'generation_pending':
                    state = deepcopy(state)
                    state['status'] = 'awaiting_generation_confirmation'
                    state['stop_reason'] = 'prior_call_outcome_unknown'
                    return state
                if state['status'] not in ('validating', 'reevaluated'):
                    return state
            else:
                state = dict(schema_version='revision-run-v2', run_id=run_id, status='validating',
                         input_hash=identity, original_plan=deepcopy(plan), current_plan=deepcopy(plan),
                         context_hash=context['context_hash'], evaluation=initial,
                         attempt_count=0, max_attempts=max_attempts, model_call_count=0,
                         generator_call_count=0, external_call_attempt_count=0, history=[], questions=[], usage=[], stop_reason=None,
                         actual_llm_execution=False, requires_human_review=True,
                         limitations=['Rule-based evaluation only; semantic/domain review still required.',
                                      'No verified welfare catalogue; not a deployed multi-agent service.'])
                self.db.execute('INSERT INTO runs VALUES (?,?,?)', (run_id, identity, canonical(state)))
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._save(state, {'step': 'validated', 'plan_hash': fingerprint(plan), 'context_hash': context['context_hash']})
        seen = {fingerprint(plan)} | {h['candidate_plan_hash'] for h in state['history']}
        while True:
            issues = state['evaluation']['issues']
            if any(i['category'] == 'hard_violation' for i in issues):
                state.update(status='needs_input', stop_reason='original_hard_violation')
                break
            editable = [i for i in issues if i['category'] == 'editable']
            if not editable:
                state.update(status='needs_input' if issues else 'awaiting_human_review',
                             stop_reason='facts_required' if issues else 'baseline_checks_complete')
                break
            if state['attempt_count'] >= max_attempts:
                state.update(status='limit_reached', stop_reason='attempt_limit')
                break
            if generator is None:
                state.update(status='needs_model', stop_reason='generator_not_configured')
                break
            state['attempt_count'] += 1
            state['generator_call_count'] += 1
            if getattr(generator, 'kind', None) == 'external_llm':
                state['external_call_attempt_count'] += 1
            state['status'] = 'generation_pending'
            payload = dict(program_plan=deepcopy(state['current_plan']), evaluation=deepcopy(state['evaluation']),
                           context=deepcopy(context), allowed_fields=['title', 'objective', 'activities', 'performance_measures'])
            self._save(state, {'step': 'generation_started'})
            started = time.monotonic()
            try:
                envelope = generator(PROMPT, payload)
                # Provenance belongs to the adapter; never infer real LLM execution from a callable.
                if not isinstance(envelope, dict) or set(envelope) != {'proposal', 'provenance'}:
                    raise ValueError('invalid generator envelope')
                provenance = envelope['provenance']
                if not isinstance(provenance, dict):
                    raise ValueError('invalid provenance')
                if provenance.get('kind') == 'external_llm':
                    if not all(provenance.get(k) for k in ('provider', 'model', 'response_id')):
                        raise ValueError('missing provider evidence')
                    state['model_call_count'] += 1
                    state['actual_llm_execution'] = True
                state['usage'].append(provenance)
                result = apply_revision(state['current_plan'], context, state['evaluation'], envelope['proposal'])
            except Exception as exc:
                state.update(status='failed', stop_reason='generation_or_validation_error')
                # Do not store arbitrary provider exception text or keys.
                self._save(state, {'step': 'failed', 'error_type': type(exc).__name__,
                                   'latency_seconds': round(time.monotonic()-started, 4)})
                return state
            candidate, reevaluation = result['candidate_plan'], result['evaluation']
            state['questions'].extend(result['questions'])
            old_ids = {i['issue_id'] for i in state['evaluation']['issues']}
            new_ids = {i['issue_id'] for i in reevaluation['issues']}
            candidate_hash = fingerprint(candidate)
            if not result['changes'] or candidate_hash in seen:
                state.update(status='no_improvement', stop_reason='no_changed_candidate')
                break
            # No new issue allowed; at least one previously editable issue must disappear.
            if new_ids - old_ids or not ({i['issue_id'] for i in editable} - new_ids):
                state.update(status='no_improvement', stop_reason='no_verified_issue_reduction')
                break
            seen.add(candidate_hash)
            state['history'].append(dict(base_plan_hash=fingerprint(state['current_plan']),
                                         candidate_plan_hash=candidate_hash, changes=result['changes']))
            state['current_plan'] = candidate
            state['evaluation'] = reevaluation
            state['status'] = 'reevaluated'
            self._save(state, {'step': 'candidate_accepted_as_draft', 'candidate_hash': candidate_hash,
                               'remaining_issue_ids': sorted(new_ids), 'latency_seconds': round(time.monotonic()-started, 4)})
        self._save(state, {'step': 'stopped', 'reason': state['stop_reason']})
        return state
