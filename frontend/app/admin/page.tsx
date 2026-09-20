import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { adminSession } from "../../lib/server/admin-access";
import AdminWorkspace from "./workspace";
import "./admin.css";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const incoming = await headers();
  const request = new Request("https://local.invalid/admin", { headers: { cookie: incoming.get("cookie") ?? "" } });
  const admin = adminSession(request);
  if (!admin) redirect("/admin/login");
  return <AdminWorkspace name={admin.name} />;
}
