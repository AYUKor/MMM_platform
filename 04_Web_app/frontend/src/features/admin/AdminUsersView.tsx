import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import type { User } from "../../shared/api/generated/admin-user-list-v1";
import type { Role as CatalogRole } from "../../shared/api/generated/admin-role-catalog-v1";
import {
  createAdminUser,
  getAdminRoles,
  getAdminUsers,
  patchAdminUser,
  revokeAdminUserSessions,
  setAdminUserEnabled,
} from "../../shared/api/auth-admin-client";
import { Button } from "../../shared/ui/Button";
import { useAuth } from "../auth/AuthProvider";
import {
  readUsersUrlState,
  usersUrlParams,
  USER_SORTS,
  USER_STATUSES,
  formatAdminDate,
  type AdminUsersUrlState,
} from "./adminModel";
import {
  AdminError,
  AdminLoading,
  AdminPage,
  EmptyAdminState,
  Modal,
} from "./AdminPageState";
import styles from "./admin.module.css";

const SORT_LABELS: Record<(typeof USER_SORTS)[number], string> = {
  created_desc: "Сначала новые",
  created_asc: "Сначала старые",
  name_asc: "По имени",
  email_asc: "По email",
  last_login_desc: "По последнему входу",
};

function mutationCopy(error: unknown): string {
  if (error && typeof error === "object" && typeof (error as { displayText?: unknown }).displayText === "string") {
    return String((error as { displayText: string }).displayText);
  }
  if (error instanceof Error && error.name === "AuthAdminError" && error.message.trim()) {
    return error.message;
  }
  return "Не удалось выполнить действие. Повторите попытку.";
}

function setUrlState(
  next: AdminUsersUrlState,
  setSearchParams: ReturnType<typeof useSearchParams>[1],
) {
  setSearchParams(usersUrlParams(next), { replace: true });
}

function UserFacts({ user }: { user: User }) {
  return (
    <dl className={styles.userFacts}>
      <div><dt>Роль</dt><dd>{user.role.title}</dd></div>
      <div><dt>Статус</dt><dd>{user.status === "active" ? "Активен" : "Отключен"}</dd></div>
      <div><dt>Создан</dt><dd>{formatAdminDate(user.created_at_utc)}</dd></div>
      <div><dt>Последний вход</dt><dd>{formatAdminDate(user.last_login_at_utc)}</dd></div>
      <div><dt>Активные сессии</dt><dd>{user.active_sessions_n}</dd></div>
    </dl>
  );
}

function CreateUserModal({
  roles,
  pending,
  error,
  onClose,
  onCreate,
}: {
  roles: readonly CatalogRole[];
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onCreate: (input: { email: string; display_name: string; password: string; role_id: "viewer" | "analyst" | "admin" }) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState<"viewer" | "analyst" | "admin">("viewer");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onCreate({ email: email.trim(), display_name: displayName.trim(), password, role_id: roleId });
      setPassword("");
    } catch {
      setPassword("");
    }
  }
  return (
    <Modal title="Новый пользователь" description="Создайте локальную pilot-учетную запись." onClose={onClose}>
      <form className={styles.modalForm} onSubmit={submit}>
        {error ? <div className={styles.inlineError} role="alert">{mutationCopy(error)}</div> : null}
        <label><span>Имя</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} minLength={2} maxLength={120} required /></label>
        <label><span>Email</span><input type="email" autoComplete="off" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} required /></label>
        <label>
          <span>Роль</span>
          <select value={roleId} onChange={(event) => setRoleId(event.target.value as typeof roleId)}>
            {roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.title}</option>)}
          </select>
        </label>
        <label>
          <span>Временный пароль</span>
          <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} maxLength={256} required />
          <small>Не менее 12 символов, минимум одна буква и одна цифра.</small>
        </label>
        <div className={styles.modalActions}>
          <Button type="button" onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" disabled={pending}>{pending ? "Создаем…" : "Создать"}</Button>
        </div>
      </form>
    </Modal>
  );
}

function EditUserModal({
  user,
  roles,
  canRename,
  canChangeRole,
  pending,
  error,
  onClose,
  onSave,
}: {
  user: User;
  roles: readonly CatalogRole[];
  canRename: boolean;
  canChangeRole: boolean;
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (input: { display_name?: string; role_id?: "viewer" | "analyst" | "admin" }) => Promise<void>;
}) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [roleId, setRoleId] = useState(user.role.role_id);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input: { display_name?: string; role_id?: typeof roleId } = {};
    if (canRename && displayName.trim() !== user.display_name) input.display_name = displayName.trim();
    if (canChangeRole && roleId !== user.role.role_id) input.role_id = roleId;
    if (Object.keys(input).length === 0) {
      onClose();
      return;
    }
    try {
      await onSave(input);
    } catch {
      // Mutation state renders the browser-safe error without closing the dialog.
    }
  }
  return (
    <Modal title="Настройки пользователя" description={user.email} onClose={onClose}>
      <form className={styles.modalForm} onSubmit={submit}>
        {error ? <div className={styles.inlineError} role="alert">{mutationCopy(error)}</div> : null}
        <label><span>Имя</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} minLength={2} maxLength={120} disabled={!canRename} required /></label>
        <label>
          <span>Роль</span>
          <select value={roleId} onChange={(event) => setRoleId(event.target.value as typeof roleId)} disabled={!canChangeRole}>
            {roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.title}</option>)}
          </select>
        </label>
        {!canChangeRole ? <p className={styles.permissionHint}>Назначение роли недоступно для текущего набора разрешений.</p> : null}
        <div className={styles.modalActions}>
          <Button type="button" onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" disabled={pending || (!canRename && !canChangeRole)}>{pending ? "Сохраняем…" : "Сохранить"}</Button>
        </div>
      </form>
    </Modal>
  );
}

type Confirmation = { kind: "enable" | "disable" | "revoke"; user: User };

export function AdminUsersView() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const state = readUsersUrlState(searchParams);
  const [searchDraft, setSearchDraft] = useState(state.search ?? "");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const usersQuery = useQuery({
    queryKey: ["phase-e", "admin-users", state],
    queryFn: ({ signal }) => getAdminUsers(state, signal),
    refetchOnWindowFocus: false,
  });
  const rolesQuery = useQuery({
    queryKey: ["phase-e", "admin-roles"],
    queryFn: ({ signal }) => getAdminRoles(signal),
    refetchOnWindowFocus: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["phase-e", "admin-users"] });
  };
  const createMutation = useMutation({ mutationFn: (input: Parameters<typeof createAdminUser>[0]) => createAdminUser(input), onSuccess: refresh });
  const patchMutation = useMutation({
    mutationFn: ({ userId, input }: { userId: string; input: { display_name?: string; role_id?: "viewer" | "analyst" | "admin" } }) => patchAdminUser(userId, input),
    onSuccess: refresh,
  });
  const statusMutation = useMutation({
    mutationFn: ({ userId, enabled }: { userId: string; enabled: boolean }) => setAdminUserEnabled(userId, enabled),
    onSuccess: refresh,
  });
  const revokeMutation = useMutation({
    mutationFn: (userId: string) => revokeAdminUserSessions(userId),
    onSuccess: refresh,
  });

  const canCreate = auth.can("admin.users.write") && auth.can("admin.roles.write");
  const canRename = auth.can("admin.users.write");
  const canChangeRole = auth.can("admin.users.write") && auth.can("admin.roles.write");
  const canRevoke = auth.can("admin.sessions.write");
  const rolesReady = Boolean(rolesQuery.data && !rolesQuery.isError);
  const rows = usersQuery.data?.items ?? [];

  function update(patch: Partial<AdminUsersUrlState>) {
    setUrlState({ ...state, ...patch }, setSearchParams);
  }

  return (
    <AdminPage
      eyebrow="Администрирование"
      title="Пользователи"
      description="Локальные учетные записи, назначенные роли и активные сессии."
      actions={canCreate && !usersQuery.isError ? <Button variant="primary" disabled={!rolesReady} onClick={() => setCreating(true)}>Добавить пользователя</Button> : null}
    >
      <form className={styles.filterBar} onSubmit={(event) => {
        event.preventDefault();
        update({ search: searchDraft.trim() || null, page: 1 });
      }}>
        <label className={styles.searchField}><span>Поиск</span><input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Имя или email" maxLength={120} /></label>
        <label><span>Роль</span><select disabled={!rolesReady} value={rolesReady ? state.role ?? "" : ""} onChange={(event) => update({ role: event.target.value ? event.target.value as AdminUsersUrlState["role"] : null, page: 1 })}><option value="">{rolesQuery.isPending ? "Загружаем роли…" : rolesQuery.isError ? "Каталог ролей недоступен" : "Все роли"}</option>{rolesReady ? rolesQuery.data?.roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.title}</option>) : null}</select></label>
        <label><span>Статус</span><select value={state.status ?? ""} onChange={(event) => update({ status: event.target.value ? event.target.value as AdminUsersUrlState["status"] : null, page: 1 })}><option value="">Все статусы</option>{USER_STATUSES.map((status) => <option key={status} value={status}>{status === "active" ? "Активен" : "Отключен"}</option>)}</select></label>
        <label><span>Сортировка</span><select value={state.sort} onChange={(event) => update({ sort: event.target.value as AdminUsersUrlState["sort"], page: 1 })}>{USER_SORTS.map((sort) => <option key={sort} value={sort}>{SORT_LABELS[sort]}</option>)}</select></label>
        <Button type="submit">Найти</Button>
      </form>

      {usersQuery.isPending ? <AdminLoading label="Загружаем пользователей" /> : null}
      {usersQuery.isError ? <AdminError error={usersQuery.error} onRetry={() => { void usersQuery.refetch(); }} /> : null}
      {usersQuery.data && !usersQuery.isError && rows.length === 0 ? <EmptyAdminState title="Пользователи не найдены" description="Измените фильтры или создайте новую учетную запись." /> : null}
      {usersQuery.data && !usersQuery.isError && rows.length > 0 ? (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead><tr><th>Пользователь</th><th>Роль</th><th>Статус</th><th>Создан</th><th>Последний вход</th><th>Сессии</th><th><span className="sr-only">Действия</span></th></tr></thead>
              <tbody>{rows.map((user) => (
                <tr key={user.user_id}>
                  <td><strong>{user.display_name}</strong><span>{user.email}</span></td>
                  <td>{user.role.title}</td>
                  <td><span className={`${styles.statusPill} ${styles[`status_${user.status}`]}`}>{user.status === "active" ? "Активен" : "Отключен"}</span></td>
                  <td>{formatAdminDate(user.created_at_utc)}</td>
                  <td>{formatAdminDate(user.last_login_at_utc)}</td>
                  <td>{user.active_sessions_n}</td>
                  <td><div className={styles.rowActions}>
                    {(canRename || canChangeRole) ? <button type="button" disabled={!rolesReady} onClick={() => { patchMutation.reset(); setEditing(user); }}>Изменить</button> : null}
                    {canRename ? <button type="button" onClick={() => setConfirmation({ kind: user.status === "active" ? "disable" : "enable", user })}>{user.status === "active" ? "Отключить" : "Включить"}</button> : null}
                    {canRevoke ? <button type="button" disabled={user.active_sessions_n === 0} onClick={() => setConfirmation({ kind: "revoke", user })}>Завершить сессии</button> : null}
                  </div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className={styles.mobileCards}>{rows.map((user) => (
            <article className={styles.userCard} key={user.user_id}>
              <header><div><strong>{user.display_name}</strong><span>{user.email}</span></div><span className={`${styles.statusPill} ${styles[`status_${user.status}`]}`}>{user.status === "active" ? "Активен" : "Отключен"}</span></header>
              <UserFacts user={user} />
              <div className={styles.cardActions}>{(canRename || canChangeRole) ? <Button disabled={!rolesReady} onClick={() => { patchMutation.reset(); setEditing(user); }}>Изменить</Button> : null}{canRename ? <Button onClick={() => setConfirmation({ kind: user.status === "active" ? "disable" : "enable", user })}>{user.status === "active" ? "Отключить" : "Включить"}</Button> : null}{canRevoke ? <Button disabled={user.active_sessions_n === 0} onClick={() => setConfirmation({ kind: "revoke", user })}>Завершить сессии</Button> : null}</div>
            </article>
          ))}</div>
          <div className={styles.pagination}>
            <span>Показано {rows.length} из {usersQuery.data.pagination.total_items}</span>
            <div><Button disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Назад</Button><span>Страница {state.page} из {Math.max(usersQuery.data.pagination.total_pages, 1)}</span><Button disabled={state.page >= usersQuery.data.pagination.total_pages} onClick={() => update({ page: state.page + 1 })}>Далее</Button></div>
          </div>
        </>
      ) : null}

      {creating && rolesReady && rolesQuery.data ? <CreateUserModal roles={rolesQuery.data.roles} pending={createMutation.isPending} error={createMutation.error} onClose={() => { createMutation.reset(); setCreating(false); }} onCreate={async (input) => { await createMutation.mutateAsync(input); setCreating(false); }} /> : null}
      {editing && rolesReady && rolesQuery.data ? <EditUserModal user={editing} roles={rolesQuery.data.roles} canRename={canRename} canChangeRole={canChangeRole} pending={patchMutation.isPending} error={patchMutation.error} onClose={() => { patchMutation.reset(); setEditing(null); }} onSave={async (input) => { await patchMutation.mutateAsync({ userId: editing.user_id, input }); setEditing(null); }} /> : null}
      {confirmation ? <Modal title={confirmation.kind === "revoke" ? "Завершить активные сессии?" : confirmation.kind === "disable" ? "Отключить пользователя?" : "Включить пользователя?"} description={`${confirmation.user.display_name} · ${confirmation.user.email}`} onClose={() => setConfirmation(null)}>
        {(statusMutation.error || revokeMutation.error) ? <div className={styles.inlineError} role="alert">{mutationCopy(statusMutation.error ?? revokeMutation.error)}</div> : null}
        <p className={styles.confirmCopy}>{confirmation.kind === "revoke" ? "Пользователю потребуется войти повторно на всех устройствах." : confirmation.kind === "disable" ? "Доступ будет закрыт, а активные сессии завершены." : "Пользователь снова сможет войти в рабочее пространство."}</p>
        <div className={styles.modalActions}><Button onClick={() => setConfirmation(null)}>Отмена</Button><Button variant="primary" disabled={statusMutation.isPending || revokeMutation.isPending} onClick={async () => { try { if (confirmation.kind === "revoke") await revokeMutation.mutateAsync(confirmation.user.user_id); else await statusMutation.mutateAsync({ userId: confirmation.user.user_id, enabled: confirmation.kind === "enable" }); setConfirmation(null); } catch { /* Keep the confirmation open and render the controlled error. */ } }}>Подтвердить</Button></div>
      </Modal> : null}
    </AdminPage>
  );
}
