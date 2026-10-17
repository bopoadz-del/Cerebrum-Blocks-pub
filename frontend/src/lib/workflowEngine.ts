import type { Node, Edge } from '@xyflow/react';

export interface ChainStep {
  block: string;
  params: Record<string, unknown>;
  label?: string;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  block: string;
  params: Record<string, unknown>;
  label?: string;
  tags?: string[];
  ui_schema?: Record<string, unknown>;
}

export interface WorkflowDocument {
  version: 1;
  name?: string;
  nodes: Node[];
  edges: Edge[];
  exportedAt?: string;
}

/** True when the graph contains a cycle (Kahn's algorithm cannot visit all nodes). */
export function hasCycle(nodes: Node[], edges: Edge[]): boolean {
  if (nodes.length === 0) return false;

  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  for (const n of nodes) {
    inDegree.set(n.id, 0);
    adj.set(n.id, []);
  }

  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!inDegree.has(e.target)) inDegree.set(e.target, 0);
    adj.get(e.source)!.push(e.target);
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
  }

  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  let visited = 0;
  while (queue.length > 0) {
    const id = queue.shift()!;
    visited += 1;
    for (const neighbor of adj.get(id) || []) {
      const newDeg = (inDegree.get(neighbor) || 0) - 1;
      inDegree.set(neighbor, newDeg);
      if (newDeg === 0) queue.push(neighbor);
    }
  }

  return visited < nodes.length;
}

/**
 * Kahn's algorithm for topological sort on a DAG of React Flow nodes.
 * Returns nodes in execution order (sources first, sinks last).
 */
export function topologicalSort(nodes: Node[], edges: Edge[]): Node[] {
  const nodeMap = new Map<string, Node>();
  for (const n of nodes) nodeMap.set(n.id, n);

  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  for (const n of nodes) {
    inDegree.set(n.id, 0);
    adj.set(n.id, []);
  }

  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!inDegree.has(e.target)) inDegree.set(e.target, 0);
    adj.get(e.source)!.push(e.target);
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
  }

  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  const sorted: Node[] = [];
  while (queue.length > 0) {
    const id = queue.shift()!;
    const node = nodeMap.get(id);
    if (node) sorted.push(node);

    for (const neighbor of adj.get(id) || []) {
      const newDeg = (inDegree.get(neighbor) || 0) - 1;
      inDegree.set(neighbor, newDeg);
      if (newDeg === 0) queue.push(neighbor);
    }
  }

  return sorted;
}

/**
 * Convert React Flow nodes/edges into chain steps for the /chain API.
 */
export function nodesToChainSteps(
  nodes: Node[],
  edges: Edge[]
): ChainStep[] {
  const sorted = topologicalSort(nodes, edges);
  return sorted.map(n => {
    const data = n.data as WorkflowNodeData;
    return {
      block: String(data.block),
      params: (data.params || {}) as Record<string, unknown>,
      label: String(data.label || data.block),
    };
  });
}

/**
 * Validate a workflow before execution.
 */
export function validateWorkflow(nodes: Node[], edges: Edge[]): { valid: boolean; error?: string } {
  if (nodes.length === 0) {
    return { valid: false, error: 'Workflow is empty. Add at least one block.' };
  }

  // Check for disconnected nodes (warning only, not an error)
  const connectedIds = new Set<string>();
  for (const e of edges) {
    connectedIds.add(e.source);
    connectedIds.add(e.target);
  }

  if (hasCycle(nodes, edges)) {
    return { valid: false, error: 'Workflow contains a cycle. Cycles are not supported in linear chain execution.' };
  }

  return { valid: true };
}

export function exportWorkflow(
  nodes: Node[],
  edges: Edge[],
  name = 'workflow'
): WorkflowDocument {
  return {
    version: 1,
    name,
    nodes,
    edges,
    exportedAt: new Date().toISOString(),
  };
}

export function parseWorkflowImport(raw: unknown): { nodes: Node[]; edges: Edge[] } {
  if (!raw || typeof raw !== 'object') {
    throw new Error('Invalid workflow file.');
  }

  const doc = raw as Partial<WorkflowDocument>;
  if (doc.version !== 1 || !Array.isArray(doc.nodes)) {
    throw new Error('Unsupported workflow format. Expected version 1 with nodes array.');
  }

  const nodes = doc.nodes.filter(
    (n): n is Node =>
      !!n &&
      typeof n === 'object' &&
      typeof (n as Node).id === 'string' &&
      typeof (n as Node).type === 'string'
  );

  if (nodes.length === 0) {
    throw new Error('Workflow file contains no valid nodes.');
  }

  const edges = Array.isArray(doc.edges)
    ? doc.edges.filter(
        (e): e is Edge =>
          !!e &&
          typeof e === 'object' &&
          typeof (e as Edge).source === 'string' &&
          typeof (e as Edge).target === 'string'
      )
    : [];

  return { nodes, edges };
}

export function downloadWorkflowJson(doc: WorkflowDocument): void {
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${doc.name || 'workflow'}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
