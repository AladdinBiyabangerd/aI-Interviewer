import { createHmac, randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";

const scrypt = promisify(scryptCallback);
const sessionLifetimeSeconds = 12 * 60 * 60;
const hashPattern = /^scrypt-v1:([A-Za-z0-9_-]{22}):([A-Za-z0-9_-]{86})$/;

export async function hashAdminPassword(password: string, salt = randomBytes(16)): Promise<string> {
  if (password.length < 20 || password.length > 256 || salt.length !== 16) throw new Error("invalid_admin_password");
  const hash = await scrypt(password, salt, 64) as Buffer;
  return `scrypt-v1:${salt.toString("base64url")}:${hash.toString("base64url")}`;
}

export async function verifyAdminPassword(password: string, stored: string): Promise<boolean> {
  const match = hashPattern.exec(stored);
  if (!match || !password || password.length > 256) return false;
  const salt = Buffer.from(match[1], "base64url");
  const expected = Buffer.from(match[2], "base64url");
  if (salt.length !== 16 || expected.length !== 64) return false;
  const received = await scrypt(password, salt, 64) as Buffer;
  return timingSafeEqual(received, expected);
}

function signature(unsigned: string, secret: string, passwordHash: string, username: string): string {
  return createHmac("sha256", secret)
    .update(`admin-session:v1:${passwordHash}:${username}:${unsigned}`)
    .digest("base64url");
}

export function issueAdminSession(secret: string, passwordHash: string, username: string, now = Date.now()): string {
  const issued = Math.floor(now / 1000);
  const unsigned = `v1.${issued}.${issued + sessionLifetimeSeconds}.${randomBytes(24).toString("base64url")}`;
  return `${unsigned}.${signature(unsigned, secret, passwordHash, username)}`;
}

export function verifyAdminSession(token: string | null, secret: string, passwordHash: string, username: string, now = Date.now()): boolean {
  if (!token || token.length > 512) return false;
  const [version, issuedText, expiresText, nonce, receivedSignature, extra] = token.split(".");
  if (version !== "v1" || extra !== undefined || !/^\d{10}$/.test(issuedText ?? "")
    || !/^\d{10}$/.test(expiresText ?? "") || !/^[A-Za-z0-9_-]{32}$/.test(nonce ?? "")
    || !/^[A-Za-z0-9_-]{43}$/.test(receivedSignature ?? "")) return false;
  const issued = Number(issuedText);
  const expires = Number(expiresText);
  const current = Math.floor(now / 1000);
  if (issued > current || expires <= current || expires - issued !== sessionLifetimeSeconds) return false;
  const unsigned = `${version}.${issuedText}.${expiresText}.${nonce}`;
  const expected = Buffer.from(signature(unsigned, secret, passwordHash, username), "ascii");
  const received = Buffer.from(receivedSignature, "ascii");
  return expected.length === received.length && timingSafeEqual(expected, received);
}
