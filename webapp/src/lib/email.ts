import nodemailer from 'nodemailer';

export type VerificationEmailResult =
  | { mode: 'smtp'; delivered: true }
  | { mode: 'log'; delivered: false; error?: string };

function smtpConfigured() {
  return Boolean(process.env.SMTP_HOST && process.env.SMTP_FROM);
}

export async function sendVerificationEmail({
  to,
  code,
}: {
  to: string;
  code: string;
}): Promise<VerificationEmailResult> {
  const appName = process.env.AUTH_EMAIL_APP_NAME || 'AI 持仓分析系统';
  const ttlMinutes = Number(process.env.AUTH_VERIFICATION_TTL_MINUTES || 10);

  if (!smtpConfigured()) {
    console.info(`[auth] verification code for ${to}: ${code} (expires in ${ttlMinutes} minutes)`);
    return { mode: 'log', delivered: false };
  }

  const port = Number(process.env.SMTP_PORT || 587);
  const secure = process.env.SMTP_SECURE === 'true' || port === 465;
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASSWORD;
  const transporter = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port,
    secure,
    auth: user && pass ? { user, pass } : undefined,
  });

  try {
    await transporter.sendMail({
      from: process.env.SMTP_FROM,
      to,
      subject: `${appName} 邮箱验证码`,
      text: `你的 ${appName} 验证码是 ${code}，${ttlMinutes} 分钟内有效。如非本人操作，请忽略本邮件。`,
      html: `
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7;color:#111827">
          <p>你好，</p>
          <p>你的 <strong>${appName}</strong> 验证码是：</p>
          <p style="font-size:28px;font-weight:700;letter-spacing:6px;color:#dc2626">${code}</p>
          <p>验证码 ${ttlMinutes} 分钟内有效。如非本人操作，请忽略本邮件。</p>
        </div>
      `,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'SMTP send failed';
    console.error(`[auth] failed to send verification email to ${to}: ${message}`);
    console.info(`[auth] verification code for ${to}: ${code} (expires in ${ttlMinutes} minutes)`);
    return { mode: 'log', delivered: false, error: message };
  }

  return { mode: 'smtp', delivered: true };
}
