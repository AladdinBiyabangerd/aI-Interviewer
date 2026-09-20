import { randomBytes, scryptSync } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const envPath = path.join(root, ".env.local");
const credentialsPath = path.join(root, ".admin-credentials");
const rotate = process.argv.includes("--rotate");
let source = "";
try { source = await readFile(envPath, "utf8"); }
catch (error) { if (error?.code !== "ENOENT") throw error; }
if (/^INTERVIEW_ADMIN_PASSWORD_HASH=/m.test(source) && !rotate) {
  throw new Error("Admin credentials exist. Pass --rotate to replace them.");
}
const username = "admin";
const password = randomBytes(32).toString("base64url");
const salt = randomBytes(16);
const hash = scryptSync(password, salt, 64);
const passwordHash = `scrypt-v1:${salt.toString("base64url")}:${hash.toString("base64url")}`;
const newline = source.includes("\r\n") ? "\r\n" : "\n";
source = source.replace(/^INTERVIEW_ADMIN_(?:USERNAME|PASSWORD_HASH)=.*(?:\r?\n|$)/gm, "");
if (source && !source.endsWith("\n")) source += newline;
source += `INTERVIEW_ADMIN_USERNAME=${username}${newline}INTERVIEW_ADMIN_PASSWORD_HASH=${passwordHash}${newline}`;
await writeFile(envPath, source, { encoding: "utf8", mode: 0o600 });
await writeFile(credentialsPath, `Username: ${username}${newline}Password: ${password}${newline}`, { encoding: "utf8", mode: 0o600 });
console.log("Admin credentials created in the ignored .admin-credentials file. The password hash is in .env.local.");
