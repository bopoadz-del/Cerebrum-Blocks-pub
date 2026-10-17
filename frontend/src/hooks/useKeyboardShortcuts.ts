import { useEffect, useCallback } from 'react';
import { useReactFlow, type Node, type Edge } from '@xyflow/react';

interface KeyboardShortcutsProps {
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onRun: () => void;
  onSave: () => void;
}

export function useKeyboardShortcuts({
  undo,
  redo,
  canUndo,
  canRedo,
  onRun,
  onSave,
}: KeyboardShortcutsProps) {
  const { getNodes, setNodes, getEdges, setEdges, deleteElements, fitView } = useReactFlow();

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      // Don't intercept shortcuts when typing in inputs, textareas, or contenteditable
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        // Allow Escape to blur even when in input
        if (event.key === 'Escape') {
          (target as HTMLElement).blur();
          return;
        }
        return;
      }

      // Undo: Ctrl+Z or Cmd+Z (without Shift)
      if ((event.ctrlKey || event.metaKey) && event.key === 'z' && !event.shiftKey) {
        event.preventDefault();
        if (canUndo) undo();
        return;
      }

      // Redo: Ctrl+Y or Ctrl+Shift+Z or Cmd+Shift+Z
      if (
        (event.ctrlKey || event.metaKey) &&
        (event.key === 'y' || (event.key === 'z' && event.shiftKey))
      ) {
        event.preventDefault();
        if (canRedo) redo();
        return;
      }

      // Run: Ctrl+Enter
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        onRun();
        return;
      }

      // Save: Ctrl+S
      if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        onSave();
        return;
      }

      // Delete / Backspace: remove selected elements
      if (event.key === 'Delete' || event.key === 'Backspace') {
        const selectedNodes = getNodes().filter((n: Node) => n.selected);
        const selectedEdges = getEdges().filter((e: Edge) => e.selected);
        if (selectedNodes.length > 0 || selectedEdges.length > 0) {
          event.preventDefault();
          deleteElements({ nodes: selectedNodes, edges: selectedEdges });
        }
        return;
      }

      // Select all: Ctrl+A
      if ((event.ctrlKey || event.metaKey) && event.key === 'a') {
        event.preventDefault();
        setNodes(getNodes().map((n: Node) => ({ ...n, selected: true })));
        setEdges(getEdges().map((e: Edge) => ({ ...e, selected: true })));
        return;
      }

      // Fit view: Ctrl+0
      if ((event.ctrlKey || event.metaKey) && event.key === '0') {
        event.preventDefault();
        fitView({ padding: 0.2, duration: 300 });
        return;
      }
    },
    [undo, redo, canUndo, canRedo, onRun, onSave, getNodes, setNodes, getEdges, setEdges, deleteElements, fitView]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}
