import { NavLink } from 'react-router';
import { Blocks, Zap } from 'lucide-react';

export default function AppHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white shrink-0">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-800">{title}</span>
          {subtitle ? (
            <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{subtitle}</span>
          ) : null}
        </div>
        <nav className="flex items-center gap-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors ${
                isActive
                  ? 'bg-gray-100 text-gray-900 font-medium'
                  : 'text-gray-500 hover:text-gray-800 hover:bg-gray-50'
              }`
            }
          >
            <Zap className="w-3.5 h-3.5" />
            Builder
          </NavLink>
          <NavLink
            to="/store"
            className={({ isActive }) =>
              `flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors ${
                isActive
                  ? 'bg-gray-100 text-gray-900 font-medium'
                  : 'text-gray-500 hover:text-gray-800 hover:bg-gray-50'
              }`
            }
          >
            <Blocks className="w-3.5 h-3.5" />
            Block Store
          </NavLink>
        </nav>
      </div>
    </div>
  );
}
