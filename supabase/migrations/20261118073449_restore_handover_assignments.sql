create table public.handover_assignments (
    assignment_id uuid primary key default gen_random_uuid(),
    task_id text not null,
    assignee_id text not null,
    assigned_by text not null,
    assigned_at timestamptz not null default now(),
    status text not null default 'assigned',
    unique (task_id, assignee_id)
);

create index handover_assignments_assigned_at_idx
    on public.handover_assignments (assigned_at desc);

alter table public.handover_assignments enable row level security;
revoke all on table public.handover_assignments from public, anon, authenticated, service_role;
grant select, insert on table public.handover_assignments to service_role;
