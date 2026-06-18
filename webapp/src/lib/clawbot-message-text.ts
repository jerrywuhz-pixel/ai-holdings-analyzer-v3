type TextCandidate = {
  text: string;
  score: number;
};

type ExtractionContext = {
  contextToken?: string | null;
  fromUserId?: string | null;
  toUserId?: string | null;
  messageId?: string | null;
};

const DIRECT_TEXT_KEYS = new Set(['text', 'content', 'body', 'message', 'msg']);
const TEXT_ITEM_KEYS = new Set(['text_item', 'textItem', 'textitem']);
const TOKENISH_KEY_PATTERN =
  /(^|_)(id|ids|uuid|token|secret|cipher|signature|sign|nonce|cursor|buf|key|account|tenant|channel|credential|conversation|user)(_id|_ids|$)/i;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function hasContentSignal(path: string[], key: string) {
  if (TOKENISH_KEY_PATTERN.test(key)) return false;
  if (DIRECT_TEXT_KEYS.has(key)) return true;
  return path.some((segment) => TEXT_ITEM_KEYS.has(segment)) && ['text', 'content'].includes(key);
}

function isTransportIdentifier(text: string, excludedValues: Set<string>) {
  const normalized = normalizeText(text);
  if (!normalized) return true;
  if (excludedValues.has(normalized)) return true;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(normalized)) {
    return true;
  }
  if (/^[0-9a-f]{24,}$/i.test(normalized)) return true;

  const containsReadableText = /[\s\u4e00-\u9fff]/.test(normalized);
  const tokenAlphabetOnly = /^[A-Za-z0-9:_./+=@-]+$/.test(normalized);
  return normalized.length >= 24 && !containsReadableText && tokenAlphabetOnly;
}

function candidateScore(path: string[], key: string, text: string) {
  let score = 0;
  if (path.some((segment) => TEXT_ITEM_KEYS.has(segment))) score += 120;
  if (key === 'text') score += 80;
  if (key === 'content' || key === 'body') score += 45;
  if (key === 'message' || key === 'msg') score += 20;
  if (/[\u4e00-\u9fff]/.test(text)) score += 30;
  if (/[A-Za-z]/.test(text)) score += 10;
  if (text.length >= 2 && text.length <= 500) score += 10;
  return score;
}

function addCandidate(
  candidates: TextCandidate[],
  value: string,
  path: string[],
  key: string,
  excludedValues: Set<string>,
) {
  const text = normalizeText(value);
  if (isTransportIdentifier(text, excludedValues)) return;
  candidates.push({
    text,
    score: candidateScore(path, key, text),
  });
}

function collectCandidates(
  value: unknown,
  candidates: TextCandidate[],
  excludedValues: Set<string>,
  path: string[] = [],
) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      collectCandidates(item, candidates, excludedValues, [...path, String(index)]);
    });
    return;
  }

  const record = asRecord(value);
  if (!record) return;

  for (const [key, nested] of Object.entries(record)) {
    if (typeof nested === 'string') {
      if (hasContentSignal(path, key)) {
        addCandidate(candidates, nested, path, key, excludedValues);
      }
      continue;
    }

    if (typeof nested === 'number' && Number.isFinite(nested) && hasContentSignal(path, key)) {
      addCandidate(candidates, String(nested), path, key, excludedValues);
      continue;
    }

    collectCandidates(nested, candidates, excludedValues, [...path, key]);
  }
}

export function extractClawbotUserText(message: unknown, context: ExtractionContext = {}) {
  const excludedValues = new Set(
    [context.contextToken, context.fromUserId, context.toUserId, context.messageId]
      .map((value) => (typeof value === 'string' ? normalizeText(value) : ''))
      .filter(Boolean),
  );
  const candidates: TextCandidate[] = [];
  collectCandidates(message, candidates, excludedValues);

  candidates.sort((left, right) => right.score - left.score || right.text.length - left.text.length);
  return candidates[0]?.text || null;
}
