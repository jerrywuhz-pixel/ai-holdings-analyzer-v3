export interface DatabaseWaitConfig {
  attempts: number;
  delayMs: number;
}

export type DatabaseProbe = () => Promise<unknown>;
export type RetryLogger = (message: string) => void;

function parseInteger(value: string | undefined, fallback: number, minimum: number): number {
  const parsed = Number.parseInt(value || "", 10);
  if (!Number.isFinite(parsed) || parsed < minimum) {
    return fallback;
  }
  return parsed;
}

function sleep(delayMs: number): Promise<void> {
  if (delayMs <= 0) {
    return Promise.resolve();
  }
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

export function getDatabaseWaitConfig(
  env: Record<string, string | undefined> = process.env,
  healthCheckMode = false,
): DatabaseWaitConfig {
  const attempts = healthCheckMode
    ? 1
    : parseInteger(env.GBRAIN_DATABASE_CONNECT_RETRIES, 12, 1);
  const delayMs = parseInteger(env.GBRAIN_DATABASE_CONNECT_RETRY_DELAY_MS, 5000, 0);

  return { attempts, delayMs };
}

export async function waitForDatabase(
  probe: DatabaseProbe,
  config: DatabaseWaitConfig,
  logger: RetryLogger = console.error,
): Promise<void> {
  let lastError: unknown;

  for (let attempt = 1; attempt <= config.attempts; attempt += 1) {
    try {
      await probe();
      return;
    } catch (error) {
      lastError = error;
      if (attempt >= config.attempts) {
        break;
      }
      logger(
        `[gbrain] Database connection failed (attempt ${attempt}/${config.attempts}); retrying in ${config.delayMs}ms`,
      );
      await sleep(config.delayMs);
    }
  }

  throw lastError;
}
