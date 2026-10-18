import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthProvider';
import { Layout } from './components/Layout';
import { Group } from './pages/Group';
import { Hst } from './pages/Hst';
import { Ohip } from './pages/Ohip';
import { Operations } from './pages/Operations';
import { Overview } from './pages/Overview';
import { Receivables } from './pages/Receivables';
import { DashboardProvider } from './state/Dashboard';

function Center({ children }: { children: React.ReactNode }) {
  return <div className="center">{children}</div>;
}

export default function App() {
  const auth = useAuth();
  switch (auth.status) {
    case 'loading':
    case 'redirecting':
      return (
        <Center>
          <p>Signing in…</p>
        </Center>
      );
    case 'error':
      return (
        <Center>
          <p className="error">{auth.error}</p>
          <button type="button" className="btn" onClick={() => auth.signIn('/')}>
            Try again
          </button>
        </Center>
      );
    case 'signed-out':
      return (
        <Center>
          <h1>Signed out</h1>
          <button type="button" className="btn" onClick={() => auth.signIn('/')}>
            Sign in
          </button>
        </Center>
      );
    case 'signed-in':
      return (
        <DashboardProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="ohip" element={<Ohip />} />
              <Route path="receivables" element={<Receivables />} />
              <Route path="hst" element={<Hst />} />
              <Route path="operations" element={<Operations />} />
              <Route path="group" element={<Group />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </DashboardProvider>
      );
  }
}
