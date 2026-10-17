import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  FileText,
  Ruler,
  DollarSign,
  AlertTriangle,
  ClipboardCheck,
  Calendar,
  ScrollText,
  ShoppingCart,
  ArrowRight,
  Loader2,
  Wrench,
} from 'lucide-react';
import type {
  DocumentInfo,
  QuantityItem,
  CostEstimate,
  Risk,
  Submittal,
  ScheduleItem,
  ContractClause,
  ProcurementItem,
  NextAction,
} from '@/types';

interface RightPanelProps {
  documentInfo?: DocumentInfo | null;
  quantities?: QuantityItem[];
  costEstimate?: CostEstimate | null;
  risks?: Risk[];
  submittals?: Submittal[];
  schedule?: ScheduleItem[];
  contract?: ContractClause[];
  procurement?: ProcurementItem[];
  nextActions?: NextAction[];
  onAction: (action: string, data?: any) => void;
  isOpen: boolean;
  onToggle: () => void;
  width: number;
  onResize: (width: number) => void;
}

interface PanelSectionProps {
  title: string;
  icon: React.ReactNode;
  defaultExpanded?: boolean;
  children: React.ReactNode;
  badge?: string;
  badgeColor?: string;
}

function PanelSection({ title, icon, defaultExpanded = false, children, badge, badgeColor }: PanelSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border-b border-[hsl(var(--border))] last:border-b-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[hsl(var(--muted))] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-[hsl(var(--amber))]">{icon}</span>
          <span className="text-sm font-medium">{title}</span>
          {badge && (
            <span
              className="text-xs px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: badgeColor, color: '#fff' }}
            >
              {badge}
            </span>
          )}
        </div>
        {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>
      {expanded && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

export default function RightPanel({
  documentInfo,
  quantities,
  costEstimate,
  risks,
  submittals,
  schedule,
  contract,
  procurement,
  nextActions,
  onAction,
  isOpen,
  onToggle,
  width,
  onResize
}: RightPanelProps) {
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [isResizing, setIsResizing] = useState(false);

  const handleAction = async (action: string) => {
    setLoadingAction(action);
    try {
      await onAction(action);
    } finally {
      setLoadingAction(null);
    }
  };

  const handleResizeStart = () => {
    setIsResizing(true);
  };

  React.useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.max(280, Math.min(500, window.innerWidth - e.clientX));
      onResize(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, onResize]);

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-40 p-2 bg-[hsl(var(--sidebar-bg))] border border-[hsl(var(--border))] rounded-l-xl shadow-lg hover:bg-[hsl(var(--muted))] transition-colors"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
    );
  }

  const hasData = documentInfo || quantities?.length || costEstimate || risks?.length || 
                  submittals?.length || schedule?.length || contract?.length || procurement?.length;

  return (
    <div
      className="relative flex flex-col h-full bg-[hsl(var(--sidebar-bg))] border-l border-[hsl(var(--border))] shrink-0 rounded-l-2xl overflow-hidden"
      style={{ width: `${width}px` }}
    >
      {/* Resize Handle */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[hsl(var(--primary))] transition-colors z-10"
        onMouseDown={handleResizeStart}
      />

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[hsl(var(--border))] shrink-0">
        <span className="font-semibold text-sm">Results</span>
        <button
          onClick={onToggle}
          className="p-1 hover:bg-[hsl(var(--muted))] rounded-md transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {!hasData ? (
          <div className="flex flex-col items-center justify-center h-full text-[hsl(var(--muted-foreground))] px-4 text-center">
            <FileText className="w-8 h-8 mb-3 opacity-30" />
            <p className="text-sm">Upload a document to see construction intelligence</p>
            <p className="text-xs mt-1 opacity-60">PDFs and images are auto-analyzed</p>
          </div>
        ) : (
          <>
            {/* Document Info */}
            {documentInfo && (
              <PanelSection title="Document Info" icon={<FileText className="w-4 h-4" />} defaultExpanded>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Type</span>
                    <span>{documentInfo.type}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Title</span>
                    <span className="text-right">{documentInfo.title}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Project</span>
                    <span>{documentInfo.project}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Pages</span>
                    <span>{documentInfo.pages}</span>
                  </div>
                  {documentInfo.author && (
                    <div className="flex justify-between">
                      <span className="text-[hsl(var(--muted-foreground))]">Author</span>
                      <span>{documentInfo.author}</span>
                    </div>
                  )}
                </div>
              </PanelSection>
            )}

            {/* Quantities */}
            {quantities && quantities.length > 0 && (
              <PanelSection
                title="Quantities"
                icon={<Ruler className="w-4 h-4" />}
                badge={`${quantities.length} items`}
                badgeColor="hsl(var(--primary))"
              >
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[hsl(var(--border))]">
                        <th className="text-left py-1.5 text-[hsl(var(--muted-foreground))] font-medium">Item</th>
                        <th className="text-right py-1.5 text-[hsl(var(--muted-foreground))] font-medium">Qty</th>
                        <th className="text-right py-1.5 text-[hsl(var(--muted-foreground))] font-medium">Unit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quantities.map((q, i) => (
                        <tr key={i} className="border-b border-[hsl(var(--border))] last:border-b-0">
                          <td className="py-1.5">{q.item}</td>
                          <td className="text-right py-1.5">{q.quantity}</td>
                          <td className="text-right py-1.5 text-[hsl(var(--muted-foreground))]">{q.unit}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </PanelSection>
            )}

            {/* Cost Estimate */}
            {costEstimate && (
              <PanelSection title="Cost Estimate" icon={<DollarSign className="w-4 h-4" />}>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Subtotal</span>
                    <span>{costEstimate.currency} {costEstimate.subtotal.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Overhead</span>
                    <span>{costEstimate.currency} {costEstimate.overhead.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[hsl(var(--muted-foreground))]">Contingency</span>
                    <span>{costEstimate.currency} {costEstimate.contingency.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between border-t border-[hsl(var(--border))] pt-2 font-semibold">
                    <span>Total</span>
                    <span className="text-[hsl(var(--primary))]">{costEstimate.currency} {costEstimate.total.toLocaleString()}</span>
                  </div>
                </div>
              </PanelSection>
            )}

            {/* Risks */}
            {risks && risks.length > 0 && (
              <PanelSection
                title="Risks"
                icon={<AlertTriangle className="w-4 h-4" />}
                badge={`${risks.length}`}
                badgeColor="hsl(var(--destructive))"
              >
                <div className="space-y-2">
                  {risks.map(risk => (
                    <div key={risk.id} className="p-2.5 bg-[hsl(var(--card))] rounded-lg border border-[hsl(var(--border))]">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className="text-xs px-2 py-0.5 rounded-full font-medium"
                          style={{
                            backgroundColor:
                              risk.severity === 'CRITICAL' ? 'hsl(var(--destructive))' :
                              risk.severity === 'HIGH'     ? 'hsl(var(--destructive))' :
                              risk.severity === 'MEDIUM'   ? 'hsl(var(--warning))' :
                                                             'hsl(var(--success))',
                            color: '#fff',
                            // CRITICAL gets the same destructive hue as HIGH but slightly bolder
                            // to keep visual hierarchy when both are present in the list.
                            fontWeight: risk.severity === 'CRITICAL' ? 700 : 500,
                          }}
                        >
                          {risk.severity}
                        </span>
                        <span className="text-xs text-[hsl(var(--muted-foreground))]">{risk.category}</span>
                      </div>
                      <p className="text-sm">{risk.description}</p>
                      {risk.mitigation && (
                        <p className="text-xs text-[hsl(var(--muted-foreground))] mt-1">{risk.mitigation}</p>
                      )}
                    </div>
                  ))}
                </div>
              </PanelSection>
            )}

            {/* Submittals */}
            {submittals && submittals.length > 0 && (
              <PanelSection
                title="Submittals"
                icon={<ClipboardCheck className="w-4 h-4" />}
                badge={`${submittals.filter(s => s.status === 'REQUIRED').length} req`}
                badgeColor="hsl(var(--warning))"
              >
                <div className="space-y-1.5">
                  {submittals.map(sub => (
                    <div key={sub.id} className="flex items-center justify-between p-2 bg-[hsl(var(--card))] rounded-md">
                      <span className="text-sm">{sub.item}</span>
                      <span
                        className="text-xs px-2 py-0.5 rounded-full"
                        style={{
                          backgroundColor: sub.status === 'APPROVED' ? 'hsl(var(--success))' : sub.status === 'PENDING' ? 'hsl(var(--warning))' : sub.status === 'REJECTED' ? 'hsl(var(--destructive))' : 'hsl(var(--muted-foreground))',
                          color: '#fff'
                        }}
                      >
                        {sub.status}
                      </span>
                    </div>
                  ))}
                </div>
              </PanelSection>
            )}

            {/* Schedule */}
            {schedule && schedule.length > 0 && (
              <PanelSection title="Schedule" icon={<Calendar className="w-4 h-4" />}>
                <div className="space-y-2">
                  {schedule.map(item => (
                    <div key={item.id} className="p-2.5 bg-[hsl(var(--card))] rounded-lg border border-[hsl(var(--border))]">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium">{item.task}</span>
                        <span
                          className="text-xs px-1.5 py-0.5 rounded"
                          style={{
                            backgroundColor: item.status === 'COMPLETED' ? 'hsl(var(--success))' : item.status === 'IN_PROGRESS' ? 'hsl(var(--primary))' : item.status === 'DELAYED' ? 'hsl(var(--destructive))' : 'hsl(var(--muted))',
                            color: item.status === 'NOT_STARTED' ? 'hsl(var(--foreground))' : '#fff'
                          }}
                        >
                          {item.status.replace('_', ' ')}
                        </span>
                      </div>
                      <div className="text-xs text-[hsl(var(--muted-foreground))]">
                        {item.start} - {item.end} ({item.duration}d)
                      </div>
                      <div className="mt-1.5 h-1.5 bg-[hsl(var(--muted))] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[hsl(var(--primary))] rounded-full transition-all"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </PanelSection>
            )}

            {/* Contract */}
            {contract && contract.length > 0 && (
              <PanelSection title="Contract" icon={<ScrollText className="w-4 h-4" />}>
                <div className="space-y-2">
                  {contract.map((clause, i) => (
                    <div key={clause.id || i} className="p-2.5 bg-[hsl(var(--card))] rounded-lg border border-[hsl(var(--border))]">
                      <div className="text-xs text-[hsl(var(--muted-foreground))] mb-1">{clause.section}</div>
                      <div className="text-sm font-medium mb-1">{clause.title}</div>
                      <div className="text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">{clause.content}</div>
                    </div>
                  ))}
                </div>
              </PanelSection>
            )}

            {/* Procurement */}
            {procurement && procurement.length > 0 && (
              <PanelSection
                title="Procurement"
                icon={<ShoppingCart className="w-4 h-4" />}
                badge={`${procurement.filter(p => p.critical).length} critical`}
                badgeColor="hsl(var(--destructive))"
              >
                <div className="space-y-2">
                  {procurement.map(item => (
                    <div
                      key={item.id}
                      className={`p-2.5 rounded-lg border ${
                        item.critical
                          ? 'bg-red-500/5 border-red-500/20'
                          : 'bg-[hsl(var(--card))] border-[hsl(var(--border))]'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium">{item.item}</span>
                        {item.critical && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-[hsl(var(--destructive))] text-white">
                            LONG LEAD
                          </span>
                        )}
                      </div>
                      <div className="flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
                        <span>{item.quantity} {item.unit}</span>
                        <span>Lead: {item.leadTime} days</span>
                      </div>
                      {item.supplier && (
                        <div className="text-xs text-[hsl(var(--muted-foreground))] mt-1">Supplier: {item.supplier}</div>
                      )}
                    </div>
                  ))}
                </div>
              </PanelSection>
            )}

            {/* Next Actions — dynamic from pipeline, fallback to defaults */}
            {hasData && (() => {
              const defaultActions: NextAction[] = [
                { action: 'procurement_list_generator', label: 'Generate Procurement List' },
                { action: 'progress_tracker', label: 'Progress Tracker' },
                { action: 'payment_certificate', label: 'Payment Certificate' },
              ];
              const actions = (nextActions && nextActions.length > 0) ? nextActions : defaultActions;
              return (
                <div className="px-4 py-4 border-t border-[hsl(var(--border))]">
                  <div className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-3">
                    Next Actions
                  </div>
                  <div className="space-y-2">
                    {actions.map(a => (
                      <button
                        key={a.action}
                        onClick={() => handleAction(a.action)}
                        disabled={!!loadingAction}
                        className="w-full flex items-center justify-between px-3 py-2 text-sm bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))] rounded-lg transition-colors text-left"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <Wrench className="w-4 h-4 text-[hsl(var(--amber))] shrink-0" />
                          <div className="min-w-0">
                            <div>{a.label}</div>
                            {a.reason && (
                              <div className="text-xs text-[hsl(var(--muted-foreground))] truncate">{a.reason}</div>
                            )}
                          </div>
                        </div>
                        {loadingAction === a.action ? (
                          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                        ) : (
                          <ArrowRight className="w-4 h-4 text-[hsl(var(--muted-foreground))] shrink-0" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })()}
          </>
        )}
      </div>
    </div>
  );
}
