"""Export the v2 backend request/resume contract without breaking v1."""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    old = json.loads((ROOT / 'docs/contracts/integration_v1.schema.json').read_text(encoding='utf-8'))
    definitions = deepcopy(old['$defs'])
    definitions['RevisionStartRequest'] = dict(type='object', additionalProperties=False,
        required=['run_id', 'analysis_id', 'planning_as_of', 'program_plan'],
        properties=dict(run_id=dict(type='string', minLength=1, maxLength=150),
                        analysis_id=dict(type='string', pattern=r'^2025(07|08|09|10|11|12)_(11230|32010)_(10G|20G|30G|40G|50G|60GU)$'),
                        planning_as_of=dict(type='string', format='date'),
                        program_plan={'$ref': '#/$defs/ProgramPlan'}, max_attempts=dict(type='integer', minimum=1, maximum=5)))
    definitions['HumanDecision'] = dict(type='object', additionalProperties=False,
        required=['action', 'reviewer', 'note'],
        properties=dict(action=dict(enum=['provide_input', 'record_review', 'reject']),
                        reviewer=dict(type='string', minLength=1, maxLength=200),
                        note=dict(type='string', minLength=1, maxLength=5000),
                        program_plan={'$ref': '#/$defs/ProgramPlan'}),
        allOf=[{'if': {'properties': {'action': {'const': 'provide_input'}}}, 'then': {'required': ['program_plan']},
                'else': {'not': {'required': ['program_plan']}}}])
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
              'title': 'Ieum-care revision integration v2',
              'description': 'Request schemas; context is loaded server-side. Cross-field version/hash/ownership checks are runtime responsibilities.',
              'anyOf': [{'$ref': '#/$defs/RevisionStartRequest'}, {'$ref': '#/$defs/HumanDecision'}], '$defs': definitions}
    path = ROOT / 'docs/contracts/revision_v2.schema.json'
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Exported v2 request/decision contract; v1 unchanged.')


if __name__ == '__main__':
    main()
