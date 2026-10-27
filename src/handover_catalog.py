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


def load_catalog_snapshot(mock_store, original_store, source_person_id, overlay):
    """Fetch request metadata concurrently, without Events or Slack message bodies."""
    from concurrent.futures import ThreadPoolExecutor
    fields = {'persons': ('person_id', 'person_id'),
              'works': ('work_id,title', 'work_id'),
              'tasks': ('task_id,title,status', 'task_id'),
              'edges': ('source_id,source_type,relation,target_id,target_type', 'source_id,relation,target_id')}

    def read(store, table):
        select, keys = fields[table]
        params = {'select': select, 'order': ','.join(k + '.asc' for k in keys.split(',')), 'limit': 500}
        if table == 'persons':
            params['person_id'] = 'eq.' + source_person_id
        elif table == 'edges':
            params['or'] = '(relation.eq.HAS_TASK,and(source_type.eq.Person,target_type.eq.Task,source_id.eq.' + source_person_id + '))'
        rows, offset = [], 0
        while True:
            page = store.request(table, params={**params, 'offset': offset})
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += len(page)

    snapshots = [{'events': []}, {'events': []}]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [(i, table, pool.submit(read, store, table))
                for i, store in enumerate((mock_store, original_store)) for table in fields]
        for i, table, job in jobs:
            snapshots[i][table] = job.result()
    merged, _, _ = overlay(*snapshots)
    return merged
