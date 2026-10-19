"""Persistent LangGraph application adapter. No server is started by importing."""
from ai.evaluation.revision_graph import RevisionGraph
from ai.evaluation.revision_v2 import load_context, validate_v2


def execute_revision(request, database, generator=None, reviewer=None):
    validate_v2(request, 'RevisionStartRequest')
    # Context is selected server-side, not accepted as arbitrary client assertions.
    allowed = {'run_id', 'analysis_id', 'planning_as_of', 'program_plan', 'max_attempts'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError('unsupported request fields')
    required = {'run_id', 'analysis_id', 'planning_as_of', 'program_plan'}
    if not required <= set(request):
        raise ValueError('required request fields missing')
    context = load_context(request['analysis_id'], planning_as_of=request['planning_as_of'])
    if request['program_plan']['analysis_id'] != request['analysis_id']:
        raise ValueError('analysis ID mismatch')
    runtime = RevisionGraph(str(database) + '.graph', generator, reviewer)
    try:
        return runtime.start(request['run_id'], request['program_plan'], context,
                             max_attempts=request.get('max_attempts', 2))
    finally:
        runtime.close()


def resume_revision(run_id, decision, database, generator=None, reviewer=None):
    runtime = RevisionGraph(str(database) + '.graph', generator, reviewer)
    try:
        return runtime.resume(run_id, decision)
    finally:
        runtime.close()
