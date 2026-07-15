import { ErrorState } from "../shared/ui/ErrorState";

export function PermissionDeniedPage() {
  return (
    <ErrorState
      tone="permission"
      title="Недостаточно прав"
      description="Authentication и admin RBAC ещё не подключены. Доступ не симулируется на клиенте."
    />
  );
}
