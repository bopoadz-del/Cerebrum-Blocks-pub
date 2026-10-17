import { useState } from 'react';
import { PanelRightClose, PanelRightOpen, Play, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { ExecutionState, StepResult } from '@/hooks/useWorkflowExecution';

interface WorkflowOutputPanelProps {
  state: ExecutionState;
  isOpen: boolean;
  onToggle: () => void;
  onRun: () => void;
}

function ResultAccordion({ result, index }: { result: StepResult; index: number }) {
  const [expanded, setExpanded] = useState(false);

  const icon =
    result.status === 'success' ? (
      <CheckCircle2 size={14} className="text-emerald-500" />
    ) : result.status === 'error' ? (
      <XCircle size={14} className="text-red-500" />
    ) : (
      <Loader2 size={14} className="text-amber-500" />
    );

  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 transition-colors text-left"
      >
        {icon}
        <span className="text-xs font-medium text-gray-700">{result.block}</span>
        <span className="text-[10px] text-gray-400 ml-auto">Step {index + 1}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2">
          {result.error ? (
            <p className="text-xs text-red-600 bg-red-50 p-2 rounded">{result.error}</p>
          ) : (
            <pre className="text-[10px] bg-gray-50 p-2 rounded overflow-auto max-h-40 text-gray-600">
              {JSON.stringify(result.output, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export default function WorkflowOutputPanel({ state, isOpen, onToggle, onRun }: WorkflowOutputPanelProps) {
  return (
    <div className={`flex flex-col h-full border-l border-gray-200 bg-white transition-all duration-200 ${isOpen ? 'w-80' : 'w-0 overflow-hidden'}`}>
      {isOpen && (
        <>
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-800">Output</h3>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={onRun}
                disabled={state.isExecuting}
                className="h-7 text-xs gap-1"
              >
                {state.isExecuting ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Play size={14} />
                )}
                {state.isExecuting ? `Running ${state.currentStep}/${state.totalSteps}` : 'Run'}
              </Button>
              <Button variant="ghost" size="icon" onClick={onToggle} className="h-7 w-7">
                <PanelRightClose size={14} />
              </Button>
            </div>
          </div>

          {/* Error Banner */}
          {state.error && (
            <div className="mx-3 mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
              {state.error}
            </div>
          )}

          {/* Step Results */}
          <ScrollArea className="flex-1">
            <div className="py-1">
              {state.results.length === 0 && !state.error && !state.isExecuting && (
                <p className="text-xs text-gray-400 text-center py-8">
                  Click Run to execute the workflow
                </p>
              )}
              {state.isExecuting && state.results.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-8 flex items-center justify-center gap-1">
                  <Loader2 size={14} className="animate-spin" />
                  Executing...
                </p>
              )}
              {state.results.map((r, i) => (
                <ResultAccordion key={i} result={r} index={i} />
              ))}
            </div>
          </ScrollArea>

          {/* Final Output */}
          {state.finalOutput && (
            <div className="p-3 border-t border-gray-200">
              <h4 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                Final Output
              </h4>
              <pre className="text-[10px] bg-gray-50 p-2 rounded overflow-auto max-h-32 text-gray-600">
                {JSON.stringify(state.finalOutput, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}

      {/* Collapsed toggle */}
      {!isOpen && (
        <button
          onClick={onToggle}
          className="absolute right-0 top-1/2 -translate-y-1/2 p-1.5 bg-white border border-gray-200 rounded-l shadow-sm hover:bg-gray-50"
        >
          <PanelRightOpen size={14} className="text-gray-500" />
        </button>
      )}
    </div>
  );
}
