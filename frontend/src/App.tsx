import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import Account from "./pages/Account";
import Aliases from "./pages/Aliases";
import Audit from "./pages/Audit";
import BusinessDetail from "./pages/BusinessDetail";
import Businesses from "./pages/Businesses";
import Dashboard from "./pages/Dashboard";
import DomainDetail from "./pages/DomainDetail";
import Domains from "./pages/Domains";
import Login from "./pages/Login";
import Mailboxes from "./pages/Mailboxes";
import NotFound from "./pages/NotFound";
import Plans from "./pages/Plans";
import ResetPassword from "./pages/ResetPassword";
import Security from "./pages/Security";
import Setup from "./pages/Setup";
import System from "./pages/System";
import Users from "./pages/Users";

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.setup_required) return <Navigate to="/setup" replace />;
  return <>{children}</>;
}

function RequireStaff({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  if (!me?.is_platform_staff) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/setup" element={<Setup />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="businesses" element={<RequireStaff><Businesses /></RequireStaff>} />
        <Route path="businesses/:id" element={<RequireStaff><BusinessDetail /></RequireStaff>} />
        <Route path="domains" element={<Domains />} />
        <Route path="domains/:id" element={<DomainDetail />} />
        <Route path="mailboxes" element={<Mailboxes />} />
        <Route path="aliases" element={<Aliases />} />
        <Route path="security" element={<Security />} />
        <Route path="audit" element={<Audit />} />
        <Route path="users" element={<Users />} />
        <Route path="plans" element={<RequireStaff><Plans /></RequireStaff>} />
        <Route path="system" element={<RequireStaff><System /></RequireStaff>} />
        <Route path="account" element={<Account />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
