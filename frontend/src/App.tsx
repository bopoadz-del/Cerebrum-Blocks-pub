import { Routes, Route, Navigate } from 'react-router';
import { ThemeProvider } from '@/context/ThemeContext';
import { Toaster } from '@/components/ui/sonner';
import WorkflowBuilder from '@/pages/WorkflowBuilder';
import Store from '@/pages/Store';

function App() {
  return (
    <ThemeProvider>
      <Routes>
        <Route path="/" element={<WorkflowBuilder />} />
        <Route path="/builder" element={<Navigate to="/" replace />} />
        <Route path="/store" element={<Store />} />
        <Route path="/store/:kitId" element={<Store />} />
      </Routes>
      <Toaster richColors position="top-right" />
    </ThemeProvider>
  );
}

export default App;
