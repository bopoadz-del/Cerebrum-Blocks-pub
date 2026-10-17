import { useState, useMemo } from 'react';
import { Search, Box } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';

export interface BlockMeta {
  name: string;
  version: string;
  description: string;
  layer: number;
  tags: string[];
  requires: string[];
  ui_schema: Record<string, unknown>;
}

const TAG_PRIORITY: Record<string, number> = {
  ai: 0, core: 1, llm: 2, chat: 3, vision: 4,
  document: 5, pdf: 6, ocr: 7, storage: 8,
  integration: 9, infrastructure: 10, security: 11,
  construction: 12, medical: 13, legal: 14, finance: 15,
  utility: 16,
};

function getPrimaryTag(tags: string[]): string {
  for (const t of tags) {
    if (TAG_PRIORITY[t] !== undefined) return t;
  }
  return tags[0] || 'general';
}

function getTagColor(tag: string): string {
  const colors: Record<string, string> = {
    ai: 'bg-violet-100 text-violet-700',
    core: 'bg-blue-100 text-blue-700',
    llm: 'bg-violet-100 text-violet-700',
    chat: 'bg-violet-100 text-violet-700',
    vision: 'bg-amber-100 text-amber-700',
    document: 'bg-emerald-100 text-emerald-700',
    pdf: 'bg-emerald-100 text-emerald-700',
    ocr: 'bg-emerald-100 text-emerald-700',
    storage: 'bg-cyan-100 text-cyan-700',
    integration: 'bg-orange-100 text-orange-700',
    infrastructure: 'bg-slate-100 text-slate-700',
    security: 'bg-red-100 text-red-700',
    construction: 'bg-teal-100 text-teal-700',
    medical: 'bg-pink-100 text-pink-700',
    legal: 'bg-indigo-100 text-indigo-700',
    finance: 'bg-lime-100 text-lime-700',
    utility: 'bg-purple-100 text-purple-700',
  };
  return colors[tag] || 'bg-gray-100 text-gray-700';
}

interface BlockPaletteProps {
  blocks: BlockMeta[];
}

export default function BlockPalette({ blocks }: BlockPaletteProps) {
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return blocks;
    return blocks.filter(
      b =>
        b.name.toLowerCase().includes(q) ||
        b.description.toLowerCase().includes(q) ||
        b.tags.some(t => t.toLowerCase().includes(q))
    );
  }, [blocks, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, BlockMeta[]>();
    for (const b of filtered) {
      const tag = getPrimaryTag(b.tags);
      if (!map.has(tag)) map.set(tag, []);
      map.get(tag)!.push(b);
    }
    // Sort groups by priority
    return Array.from(map.entries()).sort((a, b) => {
      const pa = TAG_PRIORITY[a[0]] ?? 999;
      const pb = TAG_PRIORITY[b[0]] ?? 999;
      return pa - pb;
    });
  }, [filtered]);

  const onDragStart = (e: React.DragEvent, block: BlockMeta) => {
    e.dataTransfer.setData(
      'application/json',
      JSON.stringify({ block: block.name })
    );
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div className="flex flex-col h-full w-64 bg-gray-50 border-r border-gray-200">
      <div className="p-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
          <Box size={16} />
          Blocks
        </h2>
        <div className="relative">
          <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search blocks..."
            className="h-8 pl-7 text-xs"
          />
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-3">
          {grouped.map(([tag, items]) => (
            <div key={tag}>
              <div className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider mb-1 ${getTagColor(tag)}`}>
                {tag}
              </div>
              <div className="space-y-0.5">
                {items.map(block => (
                  <div
                    key={block.name}
                    draggable
                    onDragStart={e => onDragStart(e, block)}
                    className="group flex items-center gap-2 px-2 py-1.5 rounded cursor-grab active:cursor-grabbing hover:bg-white hover:shadow-sm border border-transparent hover:border-gray-200 transition-all"
                    title={block.description}
                  >
                    <div className="w-1.5 h-1.5 rounded-full shrink-0 bg-gray-400 group-hover:bg-gray-600" />
                    <span className="text-xs font-medium text-gray-700 truncate">
                      {block.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {filtered.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-4">No blocks match</p>
          )}
        </div>
      </ScrollArea>

      <div className="p-2 border-t border-gray-200 text-[10px] text-gray-400 text-center">
        {blocks.length} blocks available
      </div>
    </div>
  );
}
