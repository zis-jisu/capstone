-- Run once before loading demo_only_work20.sql into a database without this table.
CREATE TABLE public.slack_messages (
  message_id text PRIMARY KEY,
  work_id text NOT NULL REFERENCES public.works(work_id),
  task_id text NOT NULL REFERENCES public.tasks(task_id),
  author_id text NOT NULL REFERENCES public.persons(person_id),
  author_name text NOT NULL,
  channel text, conversation_id text, thread_id text, dm_id text,
  conversation_type text, slack_ts text, parent_ts text, timestamp text,
  text text NOT NULL,
  reference_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
  raw_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE public.slack_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.slack_messages FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.slack_messages TO service_role;
