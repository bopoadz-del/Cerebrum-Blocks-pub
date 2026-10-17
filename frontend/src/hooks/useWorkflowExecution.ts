import { useState, useCallback } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { nodesToChainSteps, validateWorkflow } from '@/lib/workflowEngine';
import { api, describeError } from '@/api';

export interface StepResult {
  step: number;
  block: string;
  status: 'success' | 'error' | 'skipped';
  output?: unknown;
  error?: string;
}

export interface ExecutionState {
  isExecuting: boolean;
  currentStep: number;
  totalSteps: number;
  results: StepResult[];
  finalOutput: unknown;
  error: string | null;
}

export function useWorkflowExecution() {
  const [state, setState] = useState<ExecutionState>({
    isExecuting: false,
    currentStep: 0,
    totalSteps: 0,
    results: [],
    finalOutput: null,
    error: null,
  });

  const runWorkflow = useCallback(async (nodes: Node[], edges: Edge[]) => {
    const validation = validateWorkflow(nodes, edges);
    if (!validation.valid) {
      setState(s => ({ ...s, error: validation.error || 'Invalid workflow' }));
      return;
    }

    const steps = nodesToChainSteps(nodes, edges);
    if (steps.length === 0) {
      setState(s => ({ ...s, error: 'No executable steps found.' }));
      return;
    }

    setState({
      isExecuting: true,
      currentStep: 0,
      totalSteps: steps.length,
      results: [],
      finalOutput: null,
      error: null,
    });

    try {
      const result = await api.executeChain(steps, {});

      // The /chain response has results array
      const chainResults = result.results || [];
      const stepResults: StepResult[] = steps.map((step, i) => {
        const r = chainResults[i] as Record<string, unknown> | undefined;
        if (!r) {
          return { step: i, block: step.block, status: 'skipped' as const };
        }
        const failed =
          r.success === false ||
          r.status === 'error' ||
          r.status === 'failed';
        return {
          step: i,
          block: String(r.block || step.block),
          status: failed ? ('error' as const) : ('success' as const),
          output: r.result ?? r.output ?? r.final_output ?? r,
          error: typeof r.error === 'string' ? r.error : undefined,
        };
      });

      setState({
        isExecuting: false,
        currentStep: steps.length,
        totalSteps: steps.length,
        results: stepResults,
        finalOutput: result.final_output || result,
        error: result.success === false ? (result.error as string || 'Workflow failed') : null,
      });
    } catch (err) {
      const { message } = describeError(err);
      setState(s => ({
        ...s,
        isExecuting: false,
        error: message,
      }));
    }
  }, []);

  const reset = useCallback(() => {
    setState({
      isExecuting: false,
      currentStep: 0,
      totalSteps: 0,
      results: [],
      finalOutput: null,
      error: null,
    });
  }, []);

  return { state, runWorkflow, reset };
}
