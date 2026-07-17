import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AdminAuditPage } from "../pages/AdminAuditPage";
import { AdminIndexPage } from "../pages/AdminIndexPage";
import { AdminRolesPage } from "../pages/AdminRolesPage";
import { AdminSystemStatusPage } from "../pages/AdminSystemStatusPage";
import { AdminUsersPage } from "../pages/AdminUsersPage";
import { CalculationsPage } from "../pages/CalculationsPage";
import { HelpPage } from "../pages/HelpPage";
import { HomePage } from "../pages/HomePage";
import { JobProgressPage } from "../pages/JobProgressPage";
import { LoginPage } from "../pages/LoginPage";
import { NewCalculationPage } from "../pages/NewCalculationPage";
import { ModelPassportPage } from "../pages/ModelPassportPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import { ResultOverviewPage } from "../pages/ResultOverviewPage";
import { RequirePermission, RequireSession } from "../features/auth/RequireSession";
import { AppShell } from "../widgets/app-shell/AppShell";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <RequireSession><AppShell /></RequireSession>,
    children: [
      { index: true, element: <RequirePermission permission="workspace.read"><HomePage /></RequirePermission> },
      { path: "calculations", element: <RequirePermission permission="calculation.read"><CalculationsPage /></RequirePermission> },
      { path: "calculations/new", element: <RequirePermission permission="calculation.create"><NewCalculationPage /></RequirePermission> },
      { path: "calculations/:id/progress", element: <RequirePermission permission="calculation.read"><JobProgressPage /></RequirePermission> },
      { path: "calculations/:id/result", element: <RequirePermission permission="result.read"><ResultOverviewPage /></RequirePermission> },
      { path: "model", element: <RequirePermission permission="model.read"><ModelPassportPage /></RequirePermission> },
      { path: "help", element: <RequirePermission permission="help.read"><HelpPage /></RequirePermission> },
      { path: "admin", element: <AdminIndexPage /> },
      { path: "admin/users", element: <RequirePermission permission="admin.users.read"><AdminUsersPage /></RequirePermission> },
      { path: "admin/roles", element: <RequirePermission permission="admin.users.read"><AdminRolesPage /></RequirePermission> },
      { path: "admin/system", element: <RequirePermission permission="admin.system.read"><AdminSystemStatusPage /></RequirePermission> },
      { path: "admin/audit", element: <RequirePermission permission="admin.audit.read"><AdminAuditPage /></RequirePermission> },
      {
        path: "*",
        element: <PlaceholderPage title="Раздел не найден" description="Проверьте адрес или вернитесь в рабочее пространство." />,
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
