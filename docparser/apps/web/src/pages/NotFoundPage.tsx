import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-8xl font-bold text-neutral-200">404</p>
      <h1 className="text-xl font-semibold text-neutral-700">Page not found</h1>
      <p className="max-w-sm text-sm text-neutral-400">
        The page you&apos;re looking for doesn&apos;t exist or you don&apos;t have permission to view it.
      </p>
      <Button onClick={() => navigate('/dashboard')}>Back to Dashboard</Button>
    </div>
  );
}
