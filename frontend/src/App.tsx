import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import AdminPage from "./pages/AdminPage";
import AnomaliesPage from "./pages/AnomaliesPage";
import EquipmentDetailPage from "./pages/EquipmentDetailPage";
import EquipmentListPage from "./pages/EquipmentListPage";
import FleetOverviewPage from "./pages/FleetOverviewPage";
import LoginPage from "./pages/LoginPage";
import ModelsPage from "./pages/ModelsPage";
import PredictionsPage from "./pages/PredictionsPage";
import ReportsPage from "./pages/ReportsPage";
import SensorsPage from "./pages/SensorsPage";
import WorkOrdersPage from "./pages/WorkOrdersPage";

function RequireAuth({ children, admin }: { children: ReactNode; admin?: boolean }) {
  const { user, loading, can } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6" /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (admin && !can("admin")) return <div className="p-8 text-sm text-subtle">You need the administrator role to view this page.</div>;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<FleetOverviewPage />} />
        <Route path="equipment" element={<EquipmentListPage />} />
        <Route path="equipment/:id" element={<EquipmentDetailPage />} />
        <Route path="sensors" element={<SensorsPage />} />
        <Route path="predictions" element={<PredictionsPage />} />
        <Route path="anomalies" element={<AnomaliesPage />} />
        <Route path="work-orders" element={<WorkOrdersPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="admin" element={<RequireAuth admin><AdminPage /></RequireAuth>} />
        <Route path="*" element={<div className="p-8 text-sm text-subtle">Page not found.</div>} />
      </Route>
    </Routes>
  );
}
