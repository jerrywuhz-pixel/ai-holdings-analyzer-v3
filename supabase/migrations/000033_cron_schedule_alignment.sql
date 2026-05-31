-- Align executable cron schedules with the OpenClaw endpoint/skill contract.

UPDATE public.task_definitions
SET cron_expression = '30 15 * * 1-5',
    updated_at = now()
WHERE name = 'daily-analysis'
  AND cron_expression <> '30 15 * * 1-5';
