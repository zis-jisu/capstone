"""Work-level request metadata, derived from participation rather than ownership alone."""
PARTICIPATION = {'OWNER', 'REVIEWER', 'COLLABORATOR', 'APPROVER'}


def handover_catalog(snapshot, source_person_id):
    involved = {e['target_id'] for e in snapshot['edges']
                if e.get('source_type') == 'Person' and e.get('source_id') == source_person_id
                and e.get('target_type') == 'Task' and e.get('relation') in PARTICIPATION}
    links = [e for e in snapshot['edges'] if e.get('source_type') == 'Work'
             and e.get('target_type') == 'Task' and e.get('relation') == 'HAS_TASK']
    work_ids = {e['source_id'] for e in links if e['target_id'] in involved}
    tasks = {t['task_id']: t for t in snapshot['tasks']}
    result = []
    for work in snapshot['works']:
        if work['work_id'] not in work_ids:
            continue
        ids = sorted({e['target_id'] for e in links if e['source_id'] == work['work_id']} & tasks.keys())
        result.append({'work_id': work['work_id'], 'title': work.get('title') or work['work_id'],
                       'tasks': [{'task_id': tid, 'title': tasks[tid].get('title') or tid,
                                  'status': tasks[tid].get('status')} for tid in ids]})
    return result
