import { Navigate } from "react-router-dom";
import { firstAdminPath } from "../app/access";
import { useAuth } from "../features/auth/AuthProvider";
import { PermissionDeniedPage } from "./PermissionDeniedPage";

export function AdminIndexPage() {
  const auth = useAuth();
  const path = firstAdminPath(auth.session);
  return path ? <Navigate to={path} replace /> : <PermissionDeniedPage />;
}
