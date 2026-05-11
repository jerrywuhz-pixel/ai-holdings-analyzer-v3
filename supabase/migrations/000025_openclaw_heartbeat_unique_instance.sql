-- Holdings 3.0 P0 — OpenClaw heartbeat upsert support

CREATE UNIQUE INDEX IF NOT EXISTS idx_openclaw_heartbeat_instance_unique
  ON public.openclaw_heartbeat(instance_id);
