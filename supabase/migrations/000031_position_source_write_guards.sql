-- Add source/actionability metadata to confirmed holdings write paths.

ALTER TABLE public.position_snapshots
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS source_tier TEXT NOT NULL DEFAULT 'user_confirmed',
  ADD COLUMN IF NOT EXISTS source_actionability TEXT NOT NULL DEFAULT 'analysis_only',
  ADD COLUMN IF NOT EXISTS source_as_of TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.webapp_manual_positions
  ADD COLUMN IF NOT EXISTS source_tier TEXT NOT NULL DEFAULT 'user_confirmed',
  ADD COLUMN IF NOT EXISTS source_actionability TEXT NOT NULL DEFAULT 'analysis_only',
  ADD COLUMN IF NOT EXISTS source_as_of TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.position_snapshots.source_actionability IS
  'Actionability of the source at write time: trade_draft / analysis_only / blocked.';

COMMENT ON COLUMN public.webapp_manual_positions.source_actionability IS
  'Manual position writes are fact records by default and not realtime-trading sources.';
