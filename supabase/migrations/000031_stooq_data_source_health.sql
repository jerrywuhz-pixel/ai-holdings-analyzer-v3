-- Holdings 3.0 P0 -- register Stooq no-key quote fallback.

INSERT INTO public.data_source_health (
  source_name,
  display_name,
  status,
  priority_cn,
  priority_hk,
  priority_us
)
VALUES (
  'stooq',
  'Stooq CSV',
  'unknown',
  4,
  99,
  2
)
ON CONFLICT (source_name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  priority_cn = EXCLUDED.priority_cn,
  priority_hk = EXCLUDED.priority_hk,
  priority_us = EXCLUDED.priority_us,
  updated_at = now();
