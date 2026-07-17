import { useQuery } from "@tanstack/react-query";
import { getAdminRoles } from "../../shared/api/auth-admin-client";
import { AdminError, AdminLoading, AdminPage } from "./AdminPageState";
import styles from "./admin.module.css";

export function AdminRolesView() {
  const query = useQuery({
    queryKey: ["phase-e", "admin-roles"],
    queryFn: ({ signal }) => getAdminRoles(signal),
    refetchOnWindowFocus: false,
  });
  return (
    <AdminPage eyebrow="Администрирование" title="Роли и доступы" description="Опубликованный каталог ролей и разрешений pilot-контура.">
      {query.isPending ? <AdminLoading label="Загружаем роли" /> : null}
      {query.isError ? <AdminError error={query.error} onRetry={() => { void query.refetch(); }} /> : null}
      {query.data && !query.isError ? (
        <>
          <div className={styles.catalogMeta}><span>Версия каталога</span><strong>{query.data.catalog_version}</strong></div>
          <div className={styles.roleList}>
            {query.data.roles.map((role, index) => (
              <article className={styles.roleCard} key={role.role_id}>
                <header><span>{String(index + 1).padStart(2, "0")}</span><div><h2>{role.title}</h2><p>{role.description}</p></div></header>
                <div className={styles.permissionList}>
                  {role.permissions.map((permissionId) => {
                    const permission = query.data.permissions.find((item) => item.permission_id === permissionId);
                    if (!permission) return null;
                    return <div key={permissionId}><strong>{permission.title}</strong><span>{permission.description}</span></div>;
                  })}
                </div>
              </article>
            ))}
          </div>
          <p className={styles.catalogNote}>Назначения меняются в разделе «Пользователи». Состав ролей задается сервисом и не редактируется в интерфейсе.</p>
        </>
      ) : null}
    </AdminPage>
  );
}
