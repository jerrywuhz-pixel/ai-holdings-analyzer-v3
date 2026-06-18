type ImagePayload = {
  mediaId: string | null;
  mediaUrl: string | null;
  cdnMedia: ClawbotCdnMediaPayload | null;
  ocrText: string | null;
  imageText: string | null;
  mimeType: string | null;
};

export type ClawbotCdnMediaPayload = {
  fullUrl: string | null;
  encryptQueryParam: string | null;
  aesKeyBase64: string | null;
  aesKeyHex: string | null;
};

type ExtractionContext = {
  contextToken?: string | null;
  fromUserId?: string | null;
  toUserId?: string | null;
  messageId?: string | null;
};

const IMAGE_KEY_PATTERN = /(^|_)(image|img|photo|picture|pic|media|file|ocr)(_|\b|$)/i;
const URL_KEYS = new Set([
  'url',
  'image_url',
  'imageUrl',
  'media_url',
  'mediaUrl',
  'pic_url',
  'picUrl',
  'thumb_url',
  'thumbUrl',
  'download_url',
  'downloadUrl',
  'file_url',
  'fileUrl',
  'full_url',
  'fullUrl',
]);
const MEDIA_ID_KEYS = new Set([
  'media_id',
  'mediaId',
  'file_id',
  'fileId',
  'image_id',
  'imageId',
  'pic_id',
  'picId',
]);
const OCR_TEXT_KEYS = new Set(['ocr_text', 'ocrText']);
const IMAGE_TEXT_KEYS = new Set(['image_text', 'imageText', 'caption', 'description']);
const MIME_KEYS = new Set(['mime_type', 'mimeType', 'content_type', 'contentType']);

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function normalizeString(value: unknown) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}

function isImageUrl(value: string) {
  return /^https?:\/\/.+/i.test(value) || /^data:image\//i.test(value);
}

function pickNestedString(record: Record<string, unknown> | null, keys: string[]) {
  if (!record) return null;
  for (const key of keys) {
    const value = normalizeString(record[key]);
    if (value) return value;
  }
  return null;
}

function extractCdnMediaFromImageItem(record: Record<string, unknown>): ClawbotCdnMediaPayload | null {
  const itemList = record.item_list || record.itemList;
  if (Array.isArray(itemList)) {
    for (const item of itemList) {
      const nested = asRecord(item);
      if (!nested) continue;
      const candidate = extractCdnMediaFromImageItem(nested);
      if (candidate) return candidate;
    }
  }

  const imageItem = asRecord(record.image_item) || asRecord(record.imageItem) || record;
  const media = asRecord(imageItem.media) || asRecord(record.media);
  const thumbMedia = asRecord(imageItem.thumb_media) || asRecord(imageItem.thumbMedia);
  const selectedMedia = media || thumbMedia;

  const fullUrl = pickNestedString(selectedMedia, ['full_url', 'fullUrl', 'url']);
  const encryptQueryParam = pickNestedString(selectedMedia, ['encrypt_query_param', 'encryptQueryParam']);
  const aesKeyBase64 = pickNestedString(selectedMedia, ['aes_key', 'aesKey']);
  const aesKeyHex = pickNestedString(imageItem, ['aeskey', 'aes_key_hex', 'aesKeyHex']);

  if (!fullUrl && !encryptQueryParam) return null;
  return {
    fullUrl,
    encryptQueryParam,
    aesKeyBase64,
    aesKeyHex,
  };
}

function isTransportValue(value: string, excludedValues: Set<string>) {
  const normalized = value.trim();
  if (!normalized || excludedValues.has(normalized)) return true;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(normalized)) {
    return true;
  }
  return normalized.length >= 24 && /^[A-Za-z0-9:_./+=@-]+$/.test(normalized) && !/[\s\u4e00-\u9fff]/.test(normalized);
}

function scoreReadableText(value: string) {
  let score = 0;
  if (/[\u4e00-\u9fff]/.test(value)) score += 30;
  if (/[A-Za-z]/.test(value)) score += 10;
  if (/\d/.test(value)) score += 8;
  if (value.length >= 4 && value.length <= 1200) score += 10;
  return score;
}

export function extractClawbotImagePayload(message: unknown, context: ExtractionContext = {}): ImagePayload | null {
  const excludedValues = new Set(
    [context.contextToken, context.fromUserId, context.toUserId, context.messageId]
      .map((value) => (typeof value === 'string' ? value.trim() : ''))
      .filter(Boolean),
  );

  let hasImageSignal = false;
  let mediaId: string | null = null;
  let mediaUrl: string | null = null;
  let cdnMedia: ClawbotCdnMediaPayload | null = null;
  let mimeType: string | null = null;
  const ocrCandidates: { text: string; score: number }[] = [];
  const imageTextCandidates: { text: string; score: number }[] = [];
  const seen = new WeakSet<object>();

  function visit(value: unknown, path: string[] = []) {
    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index += 1) {
        visit(value[index], [...path, String(index)]);
      }
      return;
    }

    const record = asRecord(value);
    if (!record) return;
    if (seen.has(record)) return;
    seen.add(record);

    for (const [key, nested] of Object.entries(record)) {
      const nextPath = [...path, key];
      if (IMAGE_KEY_PATTERN.test(key) || path.some((segment) => IMAGE_KEY_PATTERN.test(segment))) {
        hasImageSignal = true;
      }

      if (!cdnMedia && (key === 'image_item' || key === 'imageItem' || key === 'item_list' || key === 'itemList')) {
        const candidate = extractCdnMediaFromImageItem(asRecord(nested) || record);
        if (candidate) {
          cdnMedia = candidate;
          hasImageSignal = true;
        }
      }

      const stringValue = normalizeString(nested);
      if (stringValue) {
        if (URL_KEYS.has(key) && isImageUrl(stringValue)) {
          mediaUrl ||= stringValue;
          hasImageSignal = true;
          continue;
        }
        if (MEDIA_ID_KEYS.has(key) && !excludedValues.has(stringValue.trim())) {
          mediaId ||= stringValue;
          hasImageSignal = true;
          continue;
        }
        if (MIME_KEYS.has(key) && /^image\//i.test(stringValue)) {
          mimeType ||= stringValue;
          hasImageSignal = true;
          continue;
        }
        if (OCR_TEXT_KEYS.has(key) && !isTransportValue(stringValue, excludedValues)) {
          ocrCandidates.push({ text: stringValue, score: 100 + scoreReadableText(stringValue) });
          hasImageSignal = true;
          continue;
        }
        if (IMAGE_TEXT_KEYS.has(key) && !isTransportValue(stringValue, excludedValues)) {
          imageTextCandidates.push({ text: stringValue, score: 80 + scoreReadableText(stringValue) });
          hasImageSignal = true;
          continue;
        }
      }

      visit(nested, nextPath);
    }
  }

  visit(message);
  if (!hasImageSignal) return null;

  ocrCandidates.sort((left, right) => right.score - left.score || right.text.length - left.text.length);
  imageTextCandidates.sort((left, right) => right.score - left.score || right.text.length - left.text.length);
  return {
    mediaId,
    mediaUrl,
    cdnMedia,
    mimeType,
    ocrText: ocrCandidates[0]?.text || null,
    imageText: imageTextCandidates[0]?.text || null,
  };
}
