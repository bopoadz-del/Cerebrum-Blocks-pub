import { useState, useCallback, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
  ReactFlowProvider,
  useReactFlow,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Play, Save, Trash2, Zap, Undo2, Redo2, Download, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import BlockPalette, { type BlockMeta } from '@/components/BlockPalette';
import WorkflowOutputPanel from '@/components/WorkflowOutputPanel';
import CerebrumNode from '@/nodes/CerebrumNode';
import { useWorkflowExecution } from '@/hooks/useWorkflowExecution';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import ZoomControls from '@/components/ZoomControls';
import { api } from '@/api';
import {
  downloadWorkflowJson,
  exportWorkflow,
  parseWorkflowImport,
  type WorkflowNodeData,
} from '@/lib/workflowEngine';
import { defaultParamsFromFields, extractParamFields } from '@/lib/blockUiSchema';
import AppHeader from '@/components/AppHeader';

const nodeTypes = {
  cerebrum: CerebrumNode,
};

const WORKFLOW_STORAGE_KEY = 'cerebrum_workflow_v1';

function FlowCanvas() {
  const { screenToFlowPosition, fitView } = useReactFlow();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [blocks, setBlocks] = useState<BlockMeta[]>([]);
  const [backendStatus, setBackendStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [importError, setImportError] = useState<string | null>(null);
  const [isOutputOpen, setIsOutputOpen] = useState(true);
  const importInputRef = useRef<HTMLInputElement>(null);
  const { state, runWorkflow, reset } = useWorkflowExecution();
  const { undo, redo, pushState, initHistory, canUndo, canRedo } = useUndoRedo(
    nodes,
    edges,
    setNodes,
    setEdges
  );

  // Fetch blocks + health on mount
  useEffect(() => {
    api.health()
      .then(() => setBackendStatus('online'))
      .catch(() => setBackendStatus('offline'));

    api.listBlocks()
      .then(data => {
        setBlocks(data.blocks);
        setBackendStatus('online');
      })
      .catch(err => {
        console.error('Failed to load blocks:', err);
        setBackendStatus('offline');
      });
  }, []);

  // Load saved workflow from LocalStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(WORKFLOW_STORAGE_KEY);
      if (saved) {
        const { nodes: savedNodes, edges: savedEdges } = JSON.parse(saved);
        if (savedNodes?.length) {
          setNodes(savedNodes);
          setEdges(savedEdges || []);
          setTimeout(() => {
            fitView({ padding: 0.2 });
            initHistory(savedNodes, savedEdges || []);
          }, 50);
        }
      }
    } catch {
      // ignore corrupted save
    }
  }, [setNodes, setEdges, fitView, initHistory]);

  // Auto-save to LocalStorage (debounced)
  useEffect(() => {
    const timer = setTimeout(() => {
      if (nodes.length > 0) {
        localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify({ nodes, edges }));
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [nodes, edges]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges(eds => {
        const newEdges = addEdge(connection, eds);
        setTimeout(() => pushState(nodes, newEdges), 0);
        return newEdges;
      });
    },
    [setEdges, nodes, pushState]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const json = e.dataTransfer.getData('application/json');
      if (!json) return;

      try {
        const { block } = JSON.parse(json);
        const blockMeta = blocks.find(b => b.name === block);
        const paramFields = extractParamFields(blockMeta?.ui_schema);
        const bounds = reactFlowWrapper.current?.getBoundingClientRect();
        if (!bounds) return;

        const position = screenToFlowPosition({
          x: e.clientX - bounds.left,
          y: e.clientY - bounds.top,
        });

        const newNode: Node = {
          id: `${block}_${Date.now()}`,
          type: 'cerebrum',
          position,
          data: {
            block,
            params: defaultParamsFromFields(paramFields),
            label: block,
            tags: blockMeta?.tags || [],
            ui_schema: blockMeta?.ui_schema || {},
          } as WorkflowNodeData,
        };

        setNodes((nds: any[]) => {
          const newNodes = [...nds, newNode];
          setTimeout(() => {
            pushState(newNodes, edges);
            fitView({ padding: 0.2, duration: 300 });
          }, 0);
          return newNodes;
        });
      } catch {
        // ignore invalid drop data
      }
    },
    [screenToFlowPosition, setNodes, edges, pushState, fitView, blocks]
  );

  const onNodeDragStop = useCallback(
    (_event: any, _node: Node, draggedNodes: Node[]) => {
      setTimeout(() => pushState(draggedNodes, edges), 0);
    },
    [edges, pushState]
  );

  const onNodesDelete = useCallback(
    (_deleted: Node[]) => {
      setTimeout(() => {
        pushState(nodes.filter((n: Node) => !_deleted.find(d => d.id === n.id)), edges);
      }, 0);
    },
    [nodes, edges, pushState]
  );

  const onEdgesDelete = useCallback(
    (_deleted: Edge[]) => {
      setTimeout(() => {
        pushState(nodes, edges.filter((e: Edge) => !_deleted.find(d => d.id === e.id)));
      }, 0);
    },
    [nodes, edges, pushState]
  );

  const handleRun = useCallback(() => {
    reset();
    runWorkflow(nodes, edges);
  }, [nodes, edges, runWorkflow, reset]);

  const handleSave = useCallback(() => {
    localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify({ nodes, edges }));
  }, [nodes, edges]);

  const handleClear = useCallback(() => {
    setNodes([]);
    setEdges([]);
    reset();
    setImportError(null);
    localStorage.removeItem(WORKFLOW_STORAGE_KEY);
    initHistory([], []);
  }, [setNodes, setEdges, reset, initHistory]);

  const handleExport = useCallback(() => {
    if (nodes.length === 0) {
      setImportError('Nothing to export — add at least one block.');
      return;
    }
    setImportError(null);
    downloadWorkflowJson(exportWorkflow(nodes, edges, 'cerebrum-workflow'));
  }, [nodes, edges]);

  const handleImportClick = useCallback(() => {
    importInputRef.current?.click();
  }, []);

  const handleImportFile = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file) return;

      const reader = new FileReader();
      reader.onload = () => {
        try {
          const parsed = parseWorkflowImport(JSON.parse(String(reader.result)));
          setNodes(parsed.nodes);
          setEdges(parsed.edges);
          reset();
          setImportError(null);
          localStorage.setItem(
            WORKFLOW_STORAGE_KEY,
            JSON.stringify({ nodes: parsed.nodes, edges: parsed.edges })
          );
          setTimeout(() => {
            fitView({ padding: 0.2, duration: 300 });
            initHistory(parsed.nodes, parsed.edges);
          }, 50);
        } catch (err) {
          setImportError(err instanceof Error ? err.message : 'Failed to import workflow.');
        }
      };
      reader.readAsText(file);
    },
    [setNodes, setEdges, reset, fitView, initHistory]
  );

  // Global keyboard shortcuts
  useKeyboardShortcuts({
    undo,
    redo,
    canUndo,
    canRedo,
    onRun: handleRun,
    onSave: handleSave,
  });

  const minimapNodeColor = (n: Node) => {
    const colors: Record<string, string> = {
      chat: '#8b5cf6',
      pdf: '#10b981',
      ocr: '#10b981',
      image: '#f59e0b',
      code: '#3b82f6',
      construction: '#14b8a6',
      bim: '#a855f7',
      memory: '#64748b',
      auth: '#ef4444',
    };
    return colors[n.data?.block as string] || '#6366f1';
  };

  return (
    <div className="flex h-full w-full">
      {/* Block Palette */}
      <BlockPalette blocks={blocks} />

      {/* Canvas + Output */}
      <div className="flex flex-1 overflow-hidden">
        <div
          ref={reactFlowWrapper}
          className="flex-1 relative"
          tabIndex={0}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onNodeDragStop={onNodeDragStop}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            deleteKeyCode={['Delete', 'Backspace']}
            selectionKeyCode="Shift"
            multiSelectionKeyCode="Control"
            snapToGrid
            snapGrid={[15, 15]}
            zoomOnScroll
            zoomOnPinch
            zoomOnDoubleClick={false}
            minZoom={0.2}
            maxZoom={4}
            defaultEdgeOptions={{
              animated: true,
              style: { stroke: '#94a3b8', strokeWidth: 2 },
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#cbd5e1" gap={20} size={1} />
            <ZoomControls />
            <MiniMap
              nodeColor={minimapNodeColor}
              maskColor="#f8fafc80"
              className="!bg-white !border !border-gray-200 !rounded-lg"
            />
            <Panel position="top-center" className="m-0">
              <div className="flex items-center gap-1.5 bg-white/90 backdrop-blur border border-gray-200 rounded-lg shadow-sm px-2 py-1.5">
                <Button
                  size="sm"
                  onClick={handleRun}
                  disabled={state.isExecuting}
                  className="h-7 text-xs gap-1 bg-emerald-600 hover:bg-emerald-700"
                >
                  {state.isExecuting ? (
                    <Zap size={14} className="animate-pulse" />
                  ) : (
                    <Play size={14} />
                  )}
                  Run
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSave}
                  className="h-7 text-xs gap-1"
                >
                  <Save size={14} />
                  Save
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleExport}
                  className="h-7 text-xs gap-1"
                  title="Export workflow JSON"
                >
                  <Download size={14} />
                  Export
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleImportClick}
                  className="h-7 text-xs gap-1"
                  title="Import workflow JSON"
                >
                  <Upload size={14} />
                  Import
                </Button>
                <input
                  ref={importInputRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  onChange={handleImportFile}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleClear}
                  className="h-7 text-xs gap-1 text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  <Trash2 size={14} />
                  Clear
                </Button>
                <div className="w-px h-4 bg-gray-200 mx-1" />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={undo}
                  disabled={!canUndo}
                  className="h-7 text-xs gap-1 px-1.5"
                  title="Undo (Ctrl+Z)"
                >
                  <Undo2 size={14} />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={redo}
                  disabled={!canRedo}
                  className="h-7 text-xs gap-1 px-1.5"
                  title="Redo (Ctrl+Y)"
                >
                  <Redo2 size={14} />
                </Button>
                <div className="w-px h-4 bg-gray-200 mx-1" />
                <span className="text-[10px] text-gray-400">
                  {nodes.length} node{nodes.length !== 1 ? 's' : ''}
                  {' · '}
                  {edges.length} edge{edges.length !== 1 ? 's' : ''}
                  {' · '}
                  <span
                    className={
                      backendStatus === 'online'
                        ? 'text-emerald-600'
                        : backendStatus === 'offline'
                          ? 'text-red-500'
                          : ''
                    }
                  >
                    {backendStatus === 'online'
                      ? 'API online'
                      : backendStatus === 'offline'
                        ? 'API offline'
                        : 'Checking API…'}
                  </span>
                </span>
              </div>
            </Panel>
            <Panel position="bottom-center" className="m-0">
              <div className="text-[10px] text-gray-400 bg-white/80 px-2 py-1 rounded">
                {importError ? (
                  <span className="text-red-500">{importError} · </span>
                ) : null}
                Ctrl+Z Undo · Ctrl+Y Redo · Ctrl+Enter Run · Ctrl+S Save · Delete Remove · Ctrl+A Select All · Ctrl+0 Fit View
              </div>
            </Panel>
          </ReactFlow>
        </div>

        <WorkflowOutputPanel
          state={state}
          isOpen={isOutputOpen}
          onToggle={() => setIsOutputOpen(v => !v)}
          onRun={handleRun}
        />
      </div>
    </div>
  );
}

export default function WorkflowBuilder() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-white flex flex-col">
      <AppHeader title="Workflow Builder" subtitle="Beta" />
      <div className="flex-1 overflow-hidden">
        <ReactFlowProvider>
          <FlowCanvas />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
