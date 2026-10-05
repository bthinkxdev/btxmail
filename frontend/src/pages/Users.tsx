import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useMe } from "../auth";
import { Badge, Confirm, Dialog, Empty, ErrorNotice, Field, Loading, PageHead, Pager, SecretReveal } from "../components/ui";
import { relative, ROLE_LABEL } from "../format";
import { PAGE_SIZE, useAction, usePaged } from "../hooks";
import type { Role, User } from "../types";
import { BusinessSelect } from "./Domains";

function CreateUser({ onClose }: { onClose: () => void }) {
  const me = useMe();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("BUSINESS_ADMIN");
  const [business, setBusiness] = useState(params.get("business") ?? "");
  const [created, setCreated] = useState<(User & { temporary_password: string }) | null>(null);

  const create = useAction(
    (body: Record<string, unknown>) => api.post<User & { temporary_password: string }>("/users/", body),
    { success: (u) => `${u.email} invited`, onSuccess: setCreated },
  );
  const err = create.error instanceof ApiError ? create.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({
      email,
      full_name: fullName,
      role,
      ...(me.is_platform_staff && role === "BUSINESS_ADMIN" ? { business: Number(business) || null } : {}),
    });
  };

  if (created) {
    return (
      <Dialog title="Portal user created" onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Done</button>}>
        <SecretReveal title={`Temporary password for ${created.email}`} value={created.temporary_password}>
          <p className="small">They will be asked to choose a new password and set up an authenticator app at first sign-in.</p>
        </SecretReveal>
      </Dialog>
    );
  }

  return (
    <Dialog
      title="Invite portal user"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" form="user-create" disabled={create.isPending || !email}>
            {create.isPending ? "Creating…" : "Create user"}
          </button>
        </>
      }
    >
      <form id="user-create" className="form" onSubmit={submit}>
        {err && !err.errors && <div className="notice bad">{err.message}</div>}
        <Field label="E-mail" error={err?.field("email")}>
          {(id) => <input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />}
        </Field>
        <Field label="Full name">
          {(id) => <input id={id} value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} />}
        </Field>
        {me.is_platform_staff && (
          <Field label="Role">
            {(id) => (
              <select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="BUSINESS_ADMIN">Business admin — manages one customer's mail</option>
                {me.is_super_admin && <option value="OPS_ADMIN">Operations admin — BThinkX support staff</option>}
                {me.is_super_admin && <option value="SUPER_ADMIN">Super admin — full platform control</option>}
              </select>
            )}
          </Field>
        )}
        {me.is_platform_staff && role === "BUSINESS_ADMIN" && (
          <BusinessSelect value={business} onChange={setBusiness} error={err?.field("business")} />
        )}
      </form>
    </Dialog>
  );
}

type UserAction = { kind: "reset" | "reset2fa" | "delete" | "toggle"; user: User } | null;

export default function Users() {
  const me = useMe();
  const [params] = useSearchParams();
  const list = usePaged<User>("/users/", { business: params.get("business") ?? undefined });
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState<UserAction>(null);
  const [password, setPassword] = useState<{ email: string; value: string } | null>(null);

  const act = useAction(
    async ({ kind, user }: NonNullable<UserAction>) => {
      if (kind === "delete") return api.del(`/users/${user.id}/`);
      if (kind === "toggle") return api.patch(`/users/${user.id}/`, { is_active: !user.is_active });
      if (kind === "reset2fa") return api.post(`/users/${user.id}/reset-2fa/`);
      const r = await api.post<{ temporary_password: string }>(`/users/${user.id}/reset-password/`);
      setPassword({ email: user.email, value: r.temporary_password });
      return r;
    },
    {
      success: (_r, v) =>
        ({ delete: "User deleted", toggle: v.user.is_active ? "User deactivated" : "User reactivated",
           reset2fa: "Two-factor reset", reset: "Password reset" })[v.kind],
      onSuccess: () => setPending(null),
    },
  );

  const canManage = (u: User) =>
    u.id !== me.id &&
    (me.is_super_admin || (me.role === "OPS_ADMIN" ? u.role === "BUSINESS_ADMIN" : u.business === me.business));

  const copy = {
    reset: { title: "Reset password", body: "A new temporary password is created. They must change it at next sign-in.", action: "Reset password" },
    reset2fa: { title: "Reset two-factor", body: "Use this when they lost their phone. They set up a new authenticator at next sign-in.", action: "Reset two-factor" },
    delete: { title: "Delete user", body: "They lose access to the portal immediately. Their past activity stays in the log.", action: "Delete user" },
    toggle: { title: "Change access", body: "Deactivated users cannot sign in.", action: "Confirm" },
  };

  return (
    <>
      <PageHead title="Portal users" intro="People who can sign in to this admin portal. Mailbox users are managed under Mailboxes.">
        <button className="btn primary" onClick={() => setCreating(true)}>Invite portal user</button>
      </PageHead>
      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty><p>No portal users.</p></Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>Security</th>
                    <th>Last sign-in</th>
                    <th><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((u) => (
                    <tr key={u.id}>
                      <td className="wrap-any">
                        <strong>{u.full_name || u.email}</strong>
                        {u.full_name && <div className="muted small">{u.email}</div>}
                      </td>
                      <td>{ROLE_LABEL[u.role]}</td>
                      {me.is_platform_staff && <td>{u.business_name ?? "BThinkX"}</td>}
                      <td>
                        <div className="actions">
                          {!u.is_active && <Badge value="DISABLED" label="Deactivated" />}
                          {u.totp_enabled ? <Badge value="OK" label="2FA on" /> : <Badge value="WARN" label="No 2FA yet" />}
                          {u.must_change_password && <Badge value="INFO" label="Temporary password" />}
                        </div>
                      </td>
                      <td className="muted small">{relative(u.last_login)}</td>
                      <td>
                        {canManage(u) && (
                          <select
                            aria-label={`Actions for ${u.email}`}
                            className="btn small"
                            value=""
                            onChange={(e) => {
                              const kind = e.target.value as NonNullable<UserAction>["kind"];
                              if (kind) setPending({ kind, user: u });
                            }}
                          >
                            <option value="">Manage…</option>
                            <option value="reset">Reset password</option>
                            {me.is_platform_staff && u.totp_enabled && <option value="reset2fa">Reset two-factor</option>}
                            <option value="toggle">{u.is_active ? "Deactivate" : "Reactivate"}</option>
                            <option value="delete">Delete</option>
                          </select>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>
      {creating && <CreateUser onClose={() => setCreating(false)} />}
      {pending && (
        <Confirm
          title={`${copy[pending.kind].title}: ${pending.user.email}`}
          body={<p>{copy[pending.kind].body}</p>}
          action={copy[pending.kind].action}
          danger={pending.kind !== "toggle" || pending.user.is_active}
          busy={act.isPending}
          onClose={() => setPending(null)}
          onConfirm={() => act.mutate(pending)}
        />
      )}
      {password && (
        <Dialog title="Password reset" onClose={() => setPassword(null)}
                footer={<button className="btn primary" onClick={() => setPassword(null)}>Done</button>}>
          <SecretReveal title={`Temporary password for ${password.email}`} value={password.value} />
        </Dialog>
      )}
    </>
  );
}
