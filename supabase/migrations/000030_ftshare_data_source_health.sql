-- Holdings 3.0 P0 -- register FTShare/OpenClaw skill market data source.

INSERT INTO public.data_source_health (
  source_name,
  display_name,
  status,
  priority_cn,
  priority_hk,
  priority_us
)
VALUES (
  'ftshare',
  'FTShare Market Data',
  'unknown',
  1,
  99,
  99
)
ON CONFLICT (source_name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  priority_cn = LEAST(public.data_source_health.priority_cn, EXCLUDED.priority_cn),
  priority_hk = EXCLUDED.priority_hk,
  priority_us = EXCLUDED.priority_us,
  updated_at = now();
