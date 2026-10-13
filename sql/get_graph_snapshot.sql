-- Supabase mock tables -> model graph JSON reconstruction RPC
-- Verified against the Link_ing project schema on 2026-10-13.

create or replace function public.get_graph_snapshot()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with node_rows as (
    select
        p.person_id::text as node_id,
        'Person'::text as node_type,
        0 as node_order,
        jsonb_build_object(
            'id', p.person_id::text,
            'type', 'Person',
            'name', p.name
        ) as node_json
    from public.persons_mock p

    union all

    select
        t.task_id::text,
        'Task',
        1,
        jsonb_build_object(
            'id', t.task_id::text,
            'type', 'Task',
            'name', coalesce(t.title, t.subject),
            'status', t.status,
            'deadline_text', t.deadline_text,
            'due_at', t.deadline_at
        )
    from public.tasks_mock t

    union all

    select
        w.work_id::text,
        'Work',
        2,
        jsonb_build_object(
            'id', w.work_id::text,
            'type', 'Work',
            'name', w.title
        )
    from public.works_mock w

    union all

    select
        e.event_id::text,
        'Event',
        3,
        jsonb_build_object(
            'id', e.event_id::text,
            'type', 'Event',
            'source_id', e.source_id,
            'action', e.action,
            'event_type', e.event_type,
            'status', e.status,
            'time_scope', e.time_scope,
            'deadline_text', e.deadline_text,
            'due_at', e.due_at,
            'memo', e.memo,
            'reference', e.reference
        )
    from public.events_mock e
),

checked_edges as (
    select
        ed.source_id,
        ed.target_id,
        upper(ed.relation) as relation,
        ed.source_type,
        ed.target_type,
        source_node.node_type as actual_source_type,
        target_node.node_type as actual_target_type,
        (
            source_node.node_id is not null
            and target_node.node_id is not null
            and ed.source_type = source_node.node_type
            and ed.target_type = target_node.node_type
            and case upper(ed.relation)
                when 'HAS_TASK' then
                    source_node.node_type = 'Work'
                    and target_node.node_type = 'Task'
                when 'HAS_EVENT' then
                    source_node.node_type = 'Task'
                    and target_node.node_type = 'Event'
                when 'OWNER' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Task'
                when 'APPROVER' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Task'
                when 'REVIEWER' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Task'
                when 'COLLABORATOR' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Task'
                when 'RELATED' then
                    source_node.node_type = 'Person'
                    and target_node.node_type in ('Task', 'Event')
                when 'ACTOR' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Event'
                when 'REQUESTER' then
                    source_node.node_type = 'Person'
                    and target_node.node_type = 'Event'
                when 'DEPENDS_ON' then
                    source_node.node_type = target_node.node_type
                    and source_node.node_type in ('Task', 'Event')
                else false
            end
        ) is true as is_valid
    from public.edges_mock ed
    left join node_rows source_node
        on source_node.node_id = ed.source_id
    left join node_rows target_node
        on target_node.node_id = ed.target_id
),

valid_edges as (
    select
        source_id,
        target_id,
        relation,
        jsonb_build_object(
            'id',
                'EDGE-ML-' || upper(
                    substr(
                        md5(
                            source_id || '|' ||
                            relation || '|' ||
                            target_id
                        ),
                        1,
                        16
                    )
                ),
            'source', source_id,
            'target', target_id,
            'relation', relation
        ) as edge_json
    from checked_edges
    where is_valid
),

validation_values as (
    select
        (select count(*) from node_rows) as node_count,
        (select count(*) from valid_edges) as edge_count,
        (select count(*) from node_rows where node_type = 'Event')
            as event_node_count,
        (select count(*) from valid_edges where relation = 'HAS_EVENT')
            as has_event_edge_count,
        (
            select count(*) - count(distinct node_id)
            from node_rows
        ) as duplicate_node_count,
        (
            select count(*) - count(distinct (source_id, relation, target_id))
            from checked_edges
        ) as duplicate_edge_count,
        (
            select count(*)
            from checked_edges
            where not is_valid
        ) as invalid_edge_count,
        (
            select count(*)
            from node_rows n
            where not exists (
                select 1
                from valid_edges e
                where e.source_id = n.node_id
                   or e.target_id = n.node_id
            )
        ) as isolated_node_count,
        not exists (
            select 1
            from node_rows event_node
            where event_node.node_type = 'Event'
              and not exists (
                  select 1
                  from valid_edges edge_row
                  where edge_row.relation = 'HAS_EVENT'
                    and edge_row.target_id = event_node.node_id
              )
        ) as event_mapping_complete
)

select jsonb_build_object(
    'schema_version', '1.0',

    'nodes',
        coalesce(
            (
                select jsonb_agg(
                    node_json
                    order by node_order, node_id
                )
                from node_rows
            ),
            '[]'::jsonb
        ),

    'edges',
        coalesce(
            (
                select jsonb_agg(
                    edge_json
                    order by relation, source_id, target_id
                )
                from valid_edges
            ),
            '[]'::jsonb
        ),

    'validation_summary',
        (
            select jsonb_build_object(
                'node_count', node_count,
                'edge_count', edge_count,
                'event_node_count', event_node_count,
                'has_event_edge_count', has_event_edge_count,
                'event_mapping_complete', event_mapping_complete,
                'duplicate_node_count', duplicate_node_count,
                'duplicate_edge_count', duplicate_edge_count,
                'invalid_edge_count', invalid_edge_count,
                'isolated_node_count', isolated_node_count,
                'is_valid',
                    duplicate_node_count = 0
                    and duplicate_edge_count = 0
                    and invalid_edge_count = 0
            )
            from validation_values
        )
);
$$;

-- Backend/model server only.
revoke all
on function public.get_graph_snapshot()
from public, anon, authenticated;

grant usage on schema public
to service_role;

grant select
on public.persons_mock,
   public.events_mock,
   public.tasks_mock,
   public.works_mock,
   public.edges_mock
to service_role;

grant execute
on function public.get_graph_snapshot()
to service_role;

notify pgrst, 'reload schema';

-- SQL Editor verification (run separately after installing the function):
-- select
--     jsonb_array_length(public.get_graph_snapshot()->'nodes') as node_count,
--     jsonb_array_length(public.get_graph_snapshot()->'edges') as edge_count,
--     public.get_graph_snapshot()->'validation_summary' as validation_summary;

