-- Holdings 3.0 P0 -- allow native and lightweight deployment mode labels.

ALTER TABLE public.openclaw_heartbeat
  DROP CONSTRAINT IF EXISTS chk_oh_deploy_mode;

ALTER TABLE public.openclaw_heartbeat
  ADD CONSTRAINT chk_oh_deploy_mode
  CHECK (deployment_mode IN ('local', 'cloud', 'local_macmini', 'lightweight_server'));
