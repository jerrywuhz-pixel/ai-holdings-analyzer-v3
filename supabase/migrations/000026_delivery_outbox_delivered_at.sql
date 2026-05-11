-- AI Holdings Analyzer 3.0 P0
-- Align delivery_outbox with the outbox worker state machine.

ALTER TABLE public.delivery_outbox
  ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;
