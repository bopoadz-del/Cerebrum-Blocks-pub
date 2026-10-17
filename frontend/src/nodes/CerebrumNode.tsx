import { memo, useMemo, useState, useCallback, useEffect } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { WorkflowNodeData } from '@/lib/workflowEngine';
import {
  extractParamFields,
  mergeParamsWithSchema,
  type ParamField,
} from '@/lib/blockUiSchema';

function getNodeColor(blockName: string, tags: string[] = []): string {
  const tagColors: Record<string, string> = {
    ai: '#8b5cf6',
    core: '#3b82f6',
    llm: '#8b5cf6',
    chat: '#8b5cf6',
    vision: '#f59e0b',
    document: '#10b981',
    pdf: '#10b981',
    ocr: '#10b981',
    storage: '#06b6d4',
    integration: '#f97316',
    infrastructure: '#64748b',
    security: '#ef4444',
    construction: '#14b8a6',
    medical: '#ec4899',
    legal: '#6366f1',
    finance: '#84cc16',
    utility: '#a855f7',
  };

  for (const tag of tags) {
    if (tagColors[tag]) return tagColors[tag];
  }

  const nameColors: Record<string, string> = {
    chat: '#8b5cf6',
    pdf: '#10b981',
    ocr: '#10b981',
    image: '#f59e0b',
    code: '#3b82f6',
    search: '#06b6d4',
    web: '#f97316',
    voice: '#ec4899',
    translate: '#14b8a6',
    construction: '#14b8a6',
    bim: '#a855f7',
    memory: '#64748b',
    auth: '#ef4444',
    monitoring: '#6366f1',
  };

  return nameColors[blockName] || '#6366f1';
}

function ParamEditor({
  field,
  value,
  onChange,
}: {
  field: ParamField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = field.label || field.name.replace(/_/g, ' ');

  if (field.type === 'boolean') {
    return (
      <div className="flex items-center gap-2 mt-0.5">
        <Switch checked={Boolean(value)} onCheckedChange={onChange} />
        <span className="text-xs text-gray-600">{Boolean(value) ? 'true' : 'false'}</span>
      </div>
    );
  }

  if (field.type === 'select' && field.options?.length) {
    return (
      <Select value={String(value ?? field.options[0] ?? '')} onValueChange={onChange}>
        <SelectTrigger className="h-7 text-xs mt-0.5">
          <SelectValue placeholder={`Select ${label}`} />
        </SelectTrigger>
        <SelectContent>
          {field.options.map(option => (
            <SelectItem key={option} value={option} className="text-xs">
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (field.type === 'json') {
    return (
      <textarea
        value={typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 0)}
        onChange={e => {
          try {
            onChange(JSON.parse(e.target.value));
          } catch {
            onChange(e.target.value);
          }
        }}
        className="w-full min-h-[56px] rounded-md border border-gray-200 px-2 py-1 text-xs mt-0.5 font-mono"
        placeholder="{}"
      />
    );
  }

  return (
    <Input
      type={field.type === 'number' ? 'number' : 'text'}
      value={String(value ?? '')}
      onChange={e =>
        onChange(field.type === 'number' ? Number(e.target.value) : e.target.value)
      }
      className="h-7 text-xs mt-0.5"
      placeholder={label}
    />
  );
}

const CerebrumNode = memo(function CerebrumNode(props: NodeProps) {
  const { data, selected } = props;
  const nodeData = data as WorkflowNodeData;
  const [isExpanded, setIsExpanded] = useState(true);

  const paramFields = useMemo(
    () => extractParamFields(nodeData.ui_schema),
    [nodeData.ui_schema]
  );

  const [params, setParams] = useState<Record<string, unknown>>(() =>
    mergeParamsWithSchema(nodeData.params as Record<string, unknown>, paramFields)
  );

  useEffect(() => {
    const merged = mergeParamsWithSchema(nodeData.params as Record<string, unknown>, paramFields);
    setParams(merged);
  }, [nodeData.params, paramFields]);

  const color = getNodeColor(String(nodeData.block), (nodeData.tags as string[]) || []);

  const updateParam = useCallback(
    (key: string, value: unknown) => {
      setParams(prev => {
        const next = { ...prev, [key]: value };
        nodeData.params = next;
        return next;
      });
    },
    [nodeData]
  );

  const schemaDriven = paramFields.length > 0;

  return (
    <div
      className={`
        min-w-[220px] max-w-[320px] rounded-lg border bg-white shadow-sm
        transition-shadow duration-200
        ${selected ? 'ring-2 ring-offset-1' : ''}
      `}
      style={{ borderColor: color, '--tw-ring-color': color } as React.CSSProperties}
    >
      <div
        className="flex items-center justify-between px-3 py-2 rounded-t-lg"
        style={{ backgroundColor: color + '15' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <span className="text-sm font-semibold truncate" style={{ color }}>
            {nodeData.block as string}
          </span>
        </div>
        <button
          onClick={() => setIsExpanded(v => !v)}
          className="p-1 rounded hover:bg-black/5 text-gray-500"
        >
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {isExpanded && (
        <div className="px-3 py-2 space-y-2">
          {!schemaDriven && Object.entries(params).length === 0 && (
            <p className="text-xs text-gray-400 italic">No parameters defined for this block</p>
          )}

          {schemaDriven
            ? paramFields.map(field => (
                <div key={field.name}>
                  <Label className="text-[10px] uppercase tracking-wide text-gray-500 font-medium">
                    {field.label || field.name}
                  </Label>
                  <ParamEditor
                    field={field}
                    value={params[field.name]}
                    onChange={value => updateParam(field.name, value)}
                  />
                </div>
              ))
            : Object.entries(params).map(([key, value]) => (
                <div key={key}>
                  <Label className="text-[10px] uppercase tracking-wide text-gray-500 font-medium">
                    {key}
                  </Label>
                  {typeof value === 'boolean' ? (
                    <div className="flex items-center gap-2 mt-0.5">
                      <Switch
                        checked={value}
                        onCheckedChange={v => updateParam(key, v)}
                      />
                      <span className="text-xs text-gray-600">{value ? 'true' : 'false'}</span>
                    </div>
                  ) : (
                    <Input
                      value={String(value ?? '')}
                      onChange={e => updateParam(key, e.target.value)}
                      className="h-7 text-xs mt-0.5"
                    />
                  )}
                </div>
              ))}
        </div>
      )}

      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-white !border-2"
        style={{ borderColor: color }}
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-white !border-2"
        style={{ borderColor: color }}
      />
    </div>
  );
});

export default CerebrumNode;
