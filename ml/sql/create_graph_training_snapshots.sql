create table if not exists public.graph_training_snapshots (
  snapshot_key text primary key,
  snapshot_at timestamptz not null,
  source_file text not null,
  graph_json jsonb not null,
  created_at timestamptz not null default now(),
  constraint graph_training_snapshots_graph_object
    check (jsonb_typeof(graph_json) = 'object'),
  constraint graph_training_snapshots_has_nodes
    check (jsonb_typeof(graph_json -> 'nodes') = 'array'),
  constraint graph_training_snapshots_has_edges
    check (jsonb_typeof(graph_json -> 'edges') = 'array')
);

alter table public.graph_training_snapshots enable row level security;

revoke all on table public.graph_training_snapshots from anon, authenticated;
grant select on table public.graph_training_snapshots to service_role;

comment on table public.graph_training_snapshots is
  'Immutable full-graph snapshots used for temporal R-GAE training. Service-role access only.';
