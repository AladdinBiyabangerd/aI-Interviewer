import Link from "next/link";
import { headers } from "next/headers";
import { adminSession } from "../../lib/server/admin-access";
import { readAccessToken } from "../../lib/server/portal-oidc";
import { Brand } from "../brand";
import AdminWorkspace from "./workspace";
import "./admin.css";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const incoming = await headers();
  const request = new Request("https://local.invalid/admin", { headers: { cookie: incoming.get("cookie") ?? "" } });
  const signedIn = Boolean(readAccessToken(request));
  const admin = await adminSession(request);
  if (!admin) return <main className="admin-gate">
    <Brand />
    <section>
      <span className="admin-kicker">Admin panel</span>
      <h1>{signedIn ? "Bu hesaba admin icazəsi verilməyib" : "Daxil olun"}</h1>
      <p>{signedIn ? "Sual bankını idarə etmək üçün admin hesabı tələb olunur." : "Hesabınıza daxil olun, sonra /admin səhifəsinə qayıdın."}</p>
      <Link className="admin-primary" href={signedIn ? "/" : "/api/auth/login"}>{signedIn ? "Ana səhifəyə qayıt" : "Hesabla daxil ol"}</Link>
    </section>
  </main>;
  return <AdminWorkspace name={admin.name} />;
}
