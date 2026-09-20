import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { adminConfigured, adminSession } from "../../../lib/server/admin-access";
import { Brand } from "../../brand";
import LoginForm from "./login-form";
import "../admin.css";

export const dynamic = "force-dynamic";

export default async function AdminLoginPage() {
  const incoming = await headers();
  const request = new Request("https://local.invalid/admin/login", { headers: { cookie: incoming.get("cookie") ?? "" } });
  if (adminSession(request)) redirect("/admin");
  return <main className="admin-gate">
    <Brand />
    <section>
      <span className="admin-kicker">Admin panel</span>
      <h1>Daxil olun</h1>
      <p>Sual bankını idarə etmək üçün admin hesabınızla daxil olun.</p>
      {adminConfigured() ? <LoginForm /> : <p className="admin-login-warning">Admin hesabı serverdə hələ qurulmayıb.</p>}
      <Link className="admin-back" href="/">Ana səhifəyə qayıt</Link>
    </section>
  </main>;
}
