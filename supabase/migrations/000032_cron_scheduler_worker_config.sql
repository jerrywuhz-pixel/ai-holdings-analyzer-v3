-- Holdings 3.0 cron scheduler worker activation.
--
-- task_definitions remains the source of truth for schedules. The scheduler
-- worker only executes rows with config.scheduler.enabled=true and an
-- endpoint_path, so design-only task definitions can stay present without
-- generating noisy failed job_runs.

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_runs_scheduler_dedupe
  ON public.job_runs ((config->'scheduler'->>'dedupe_key'))
  WHERE config->'scheduler'->>'source' = 'openclaw-cron-scheduler';

UPDATE public.task_definitions
SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
  'scheduler',
  jsonb_build_object(
    'enabled', true,
    'executor', 'openclaw_http',
    'endpoint_path', '/api/cron/daily-scan'
  )
),
updated_at = now()
WHERE name = 'daily-analysis';

UPDATE public.task_definitions
SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
  'scheduler',
  jsonb_build_object(
    'enabled', true,
    'executor', 'openclaw_http',
    'endpoint_path', '/api/cron/heartbeat'
  )
),
updated_at = now()
WHERE name = 'heartbeat';

UPDATE public.task_definitions
SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
  'scheduler',
  jsonb_build_object(
    'enabled', true,
    'executor', 'openclaw_http',
    'endpoint_path', '/api/cron/profit-taking'
  )
),
updated_at = now()
WHERE name = 'daily-profit-taking';

INSERT INTO public.task_definitions (
  name,
  job_type,
  cron_expression,
  skill_name,
  config,
  is_enabled,
  timeout_seconds,
  max_retries
)
VALUES
  (
    'stale-jobs-check',
    'stale_jobs_check',
    '*/10 * * * *',
    'heartbeat',
    jsonb_build_object(
      'trigger_type', 'cron',
      'scheduler',
      jsonb_build_object(
        'enabled', true,
        'executor', 'openclaw_http',
        'endpoint_path', '/api/cron/stale-jobs'
      )
    ),
    true,
    60,
    3
  ),
  (
    'sellput-score',
    'sellput_score',
    '20 16 * * 1-5',
    'quant-options-strategy',
    jsonb_build_object(
      'trigger_type', 'cron',
      'scheduler',
      jsonb_build_object(
        'enabled', true,
        'executor', 'openclaw_http',
        'endpoint_path', '/api/cron/sellput-score',
        'payload', jsonb_build_object(
          'mode', 'scan',
          'contracts', jsonb_build_array(),
          'min_score', 70
        )
      )
    ),
    true,
    300,
    3
  )
ON CONFLICT (name) DO UPDATE SET
  job_type = EXCLUDED.job_type,
  cron_expression = EXCLUDED.cron_expression,
  skill_name = EXCLUDED.skill_name,
  config = EXCLUDED.config,
  is_enabled = EXCLUDED.is_enabled,
  timeout_seconds = EXCLUDED.timeout_seconds,
  max_retries = EXCLUDED.max_retries,
  updated_at = now();

UPDATE public.task_definitions
SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
  'scheduler',
  jsonb_build_object(
    'enabled', false,
    'disabled_reason', 'executor_not_implemented'
  )
),
updated_at = now()
WHERE name IN ('daily-review', 'weekly-report', 'gbrain-sync', 'gbrain-dream')
  AND COALESCE(COALESCE(config, '{}'::jsonb)->'scheduler'->>'enabled', 'false') <> 'true';
