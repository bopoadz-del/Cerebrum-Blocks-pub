import { useCallback, useRef, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';

interface HistoryState {
  nodes: Node[];
  edges: Edge[];
}

export function useUndoRedo(
  _nodes: Node[],
  _edges: Edge[],
  setNodes: (nodes: Node[]) => void,
  setEdges: (edges: Edge[]) => void
) {
  const historyRef = useRef<HistoryState[]>([]);
  const indexRef = useRef(-1);
  const isUndoingRef = useRef(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const pushState = useCallback((newNodes: Node[], newEdges: Edge[]) => {
    if (isUndoingRef.current) {
      isUndoingRef.current = false;
      return;
    }
    // Trim any future states if we're not at the end
    historyRef.current = historyRef.current.slice(0, indexRef.current + 1);
    historyRef.current.push({
      nodes: JSON.parse(JSON.stringify(newNodes)),
      edges: JSON.parse(JSON.stringify(newEdges)),
    });
    indexRef.current = historyRef.current.length - 1;
    setCanUndo(indexRef.current > 0);
    setCanRedo(false);
  }, []);

  const undo = useCallback(() => {
    if (indexRef.current <= 0) return;
    indexRef.current -= 1;
    isUndoingRef.current = true;
    const state = historyRef.current[indexRef.current];
    setNodes(JSON.parse(JSON.stringify(state.nodes)));
    setEdges(JSON.parse(JSON.stringify(state.edges)));
    setCanUndo(indexRef.current > 0);
    setCanRedo(true);
  }, [setNodes, setEdges]);

  const redo = useCallback(() => {
    if (indexRef.current >= historyRef.current.length - 1) return;
    indexRef.current += 1;
    isUndoingRef.current = true;
    const state = historyRef.current[indexRef.current];
    setNodes(JSON.parse(JSON.stringify(state.nodes)));
    setEdges(JSON.parse(JSON.stringify(state.edges)));
    setCanUndo(true);
    setCanRedo(indexRef.current < historyRef.current.length - 1);
  }, [setNodes, setEdges]);

  const initHistory = useCallback((initialNodes: Node[], initialEdges: Edge[]) => {
    historyRef.current = [{
      nodes: JSON.parse(JSON.stringify(initialNodes)),
      edges: JSON.parse(JSON.stringify(initialEdges)),
    }];
    indexRef.current = 0;
    setCanUndo(false);
    setCanRedo(false);
  }, []);

  return { undo, redo, pushState, initHistory, canUndo, canRedo };
}
