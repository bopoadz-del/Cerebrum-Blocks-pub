import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  CheckCircle2,
  Circle,
  Clock,
  Copy,
  ExternalLink,
  FolderOpen,
  Loader2,
  Package,
  Search,
  XCircle,
} from 'lucide-react';
import AppHeader from '@/components/AppHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  api,
  describeError,
  type ContainerKitDetail,
  type ContainerKitInstallResult,
  type ContainerKitSummary,
} from '@/api';
import { toast } from 'sonner';

const REQUIRED_GENERIC_BLOCKS = ['pdf', 'ocr', 'chat', 'image'] as const;
const CONSTRUCTION_ARTIFACT_COUNT = 32;
const DOCS_GENERIC_BLOCKS_URL =
  'https://github.com/bopoadz-del/Cerebrum-Blocks/blob/main/docs/generic_blocks.md';

type AvailabilityFilter = 'all' | 'available' | 'coming_soon';

function tagColor(tag: string): string {
  const colors: Record<string, string> = {
    domain: 'bg-teal-100 text-teal-700',
    container: 'bg-blue-100 text-blue-700',
    aec: 'bg-amber-100 text-amber-700',
    construction: 'bg-emerald-100 text-emerald-700',
    bim: 'bg-violet-100 text-violet-700',
  };
  return colors[tag] || 'bg-gray-100 text-gray-700';
}

function isKitComingSoon(kit: ContainerKitSummary): boolean {
  return Boolean(kit.coming_soon || kit.status === 'coming_soon');
}

function KitStatusBadge({ kit }: { kit: ContainerKitSummary }) {
  if (isKitComingSoon(kit)) {
    return (
      <Badge variant="outline" className="text-slate-600 border-slate-200 bg-slate-50">
        Coming Soon
      </Badge>
    );
  }
  if (!kit.bundle_ready) {
    return (
      <Badge variant="outline" className="text-amber-700 border-amber-200 bg-amber-50">
        Bundle pending
      </Badge>
    );
  }
  return (
    <Badge className="bg-emerald-600 hover:bg-emerald-600 text-white border-transparent">
      <CheckCircle2 className="w-3 h-3" />
      Bundle ready
    </Badge>
  );
}

function isKitInstallable(kit: ContainerKitSummary): boolean {
  if (kit.bundle_ready && !isKitComingSoon(kit)) return true;
  return Boolean(kit.skeleton_installable);
}

function matchesAvailabilityFilter(kit: ContainerKitSummary, filter: AvailabilityFilter): boolean {
  if (filter === 'available') return isKitInstallable(kit);
  if (filter === 'coming_soon') return isKitComingSoon(kit);
  return true;
}

function KitCard({
  kit,
  installed,
  onSelect,
}: {
  kit: ContainerKitSummary;
  installed: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md py-4 gap-4"
      onClick={() => onSelect(kit.id)}
    >
      <CardHeader className="px-4 pb-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-base truncate">{kit.name}</CardTitle>
            <CardDescription className="text-xs mt-1">v{kit.version}</CardDescription>
          </div>
          <KitStatusBadge kit={kit} />
        </div>
      </CardHeader>
      <CardContent className="px-4 pt-0">
        <p className="text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]">
          {kit.description || 'No description'}
        </p>
        {kit.tags?.length ? (
          <div className="flex flex-wrap gap-1 mt-3">
            {kit.tags.slice(0, 4).map(tag => (
              <span key={tag} className={`text-[10px] px-1.5 py-0.5 rounded-full ${tagColor(tag)}`}>
                {tag}
              </span>
            ))}
          </div>
        ) : null}
      </CardContent>
      <CardFooter className="px-4 pt-0 flex items-center justify-between">
        <span className="text-[10px] text-gray-400 font-mono">{kit.id}</span>
        {installed ? (
          <Badge variant="secondary" className="text-[10px]">
            Installed
          </Badge>
        ) : null}
      </CardFooter>
    </Card>
  );
}

function InstallSuccessPanel({
  kit,
  result,
  onDismiss,
}: {
  kit: ContainerKitDetail;
  result: ContainerKitInstallResult;
  onDismiss: () => void;
}) {
  const copiedCount = result.copied?.length ?? 0;
  const envHint = `CEREBRUM_DOMAIN_KITS=${kit.id}`;

  const copyEnvHint = () => {
    void navigator.clipboard.writeText(envHint);
    toast.success('Copied to clipboard', { description: envHint });
  };

  return (
    <Card className="border-emerald-200 bg-emerald-50/50 py-4 gap-4">
      <CardHeader className="px-4 pb-0">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          <div>
            <CardTitle className="text-base text-emerald-900">Install complete</CardTitle>
            <CardDescription className="text-emerald-800/80 mt-1">
              {kit.name} v{result.version ?? kit.version} — {copiedCount} file
              {copiedCount === 1 ? '' : 's'} copied
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-4 space-y-3">
        {result.target_root ? (
          <div className="flex items-start gap-2 text-xs text-emerald-900/80">
            <FolderOpen className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>
              Installed to <span className="font-mono">{result.target_root}</span>
            </span>
          </div>
        ) : null}
        <div className="rounded-md border border-emerald-200 bg-white px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Enable on next boot
          </p>
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono text-gray-800 flex-1 truncate">{envHint}</code>
            <Button variant="ghost" size="sm" className="h-7 px-2 shrink-0" onClick={copyEnvHint}>
              <Copy className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
        <a
          href={DOCS_GENERIC_BLOCKS_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-emerald-800 hover:underline"
        >
          Generic blocks &amp; kit enablement docs
          <ExternalLink className="w-3 h-3" />
        </a>
      </CardContent>
      <CardFooter className="px-4 pt-0">
        <Button variant="outline" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      </CardFooter>
    </Card>
  );
}

function PreInstallChecklistModal({
  kit,
  open,
  installing,
  genericBlockStatus,
  onClose,
  onConfirm,
}: {
  kit: ContainerKitDetail;
  open: boolean;
  installing: boolean;
  genericBlockStatus: Record<string, boolean>;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const isConstruction = kit.id === 'construction';
  const artifactCount = kit.artifacts?.length ?? (isConstruction ? CONSTRUCTION_ARTIFACT_COUNT : 0);
  const installable = isKitInstallable(kit);
  const allBlocksPresent = REQUIRED_GENERIC_BLOCKS.every(b => genericBlockStatus[b]);

  return (
    <Dialog open={open} onOpenChange={v => !v && !installing && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Install checklist</DialogTitle>
          <DialogDescription>
            Review prerequisites before installing <span className="font-medium">{kit.name}</span>.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Kit status
            </p>
            <div className="flex items-center gap-2">
              <KitStatusBadge kit={kit} />
              {isKitComingSoon(kit) ? (
                <span className="text-xs text-slate-600">Not available for install yet</span>
              ) : kit.bundle_ready ? (
                <span className="text-xs text-emerald-700">Ready to install</span>
              ) : (
                <span className="text-xs text-amber-700">Bundle not published</span>
              )}
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Required generic blocks
            </p>
            <ul className="space-y-1.5">
              {REQUIRED_GENERIC_BLOCKS.map(block => {
                const present = genericBlockStatus[block];
                return (
                  <li key={block} className="flex items-center gap-2 text-xs">
                    {present ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                    ) : (
                      <Circle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                    )}
                    <span className="font-mono">{block}</span>
                    <span className="text-muted-foreground">
                      {present ? 'available' : 'not detected on instance'}
                    </span>
                  </li>
                );
              })}
            </ul>
            {!allBlocksPresent ? (
              <p className="text-[10px] text-amber-700 mt-2">
                Generic blocks ship with Virgin Fork by default. Missing blocks may indicate a
                trimmed deployment.
              </p>
            ) : null}
          </div>

          {isConstruction ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div className="text-xs text-amber-900">
                <p className="font-medium">Construction AEC Suite</p>
                <p className="mt-0.5 text-amber-800">
                  This kit copies <strong>{artifactCount} artifacts</strong> (blocks, prompts,
                  schemas, and domain modules) into your project root.
                </p>
              </div>
            </div>
          ) : null}

          <div className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600 flex gap-2">
            <FolderOpen className="w-3.5 h-3.5 shrink-0 mt-0.5 text-gray-400" />
            <span>
              Files install to the <strong>project root</strong> returned by the API (read-only
              target — not configurable from this UI).
            </span>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={installing}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={installing || !installable} className="gap-2">
            {installing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Installing…
              </>
            ) : (
              <>
                <Package className="w-4 h-4" />
                Confirm install
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function KitDetailView({
  kit,
  installing,
  installed,
  installResult,
  genericBlockStatus,
  checklistOpen,
  onOpenChecklist,
  onCloseChecklist,
  onConfirmInstall,
  onDismissSuccess,
  onBack,
}: {
  kit: ContainerKitDetail;
  installing: boolean;
  installed: boolean;
  installResult: ContainerKitInstallResult | null;
  genericBlockStatus: Record<string, boolean>;
  checklistOpen: boolean;
  onOpenChecklist: () => void;
  onCloseChecklist: () => void;
  onConfirmInstall: () => void;
  onDismissSuccess: () => void;
  onBack: () => void;
}) {
  const sourceRepo = kit.source?.repo;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Button variant="ghost" size="sm" onClick={onBack} className="gap-1.5 -ml-2">
        <ArrowLeft className="w-4 h-4" />
        Back to catalog
      </Button>

      {installResult ? (
        <InstallSuccessPanel kit={kit} result={installResult} onDismiss={onDismissSuccess} />
      ) : null}

      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{kit.name}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            v{kit.version}
            {kit.author ? ` · ${kit.author}` : ''}
          </p>
          <p className="text-sm text-gray-600 mt-3">{kit.description}</p>
          {kit.tags?.length ? (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {kit.tags.map(tag => (
                <span key={tag} className={`text-xs px-2 py-0.5 rounded-full ${tagColor(tag)}`}>
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-start sm:items-end gap-2 shrink-0">
          <KitStatusBadge kit={kit} />
          <Button
            onClick={onOpenChecklist}
            disabled={installing || !isKitInstallable(kit)}
            className="gap-2"
          >
            {installing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Installing…
              </>
            ) : installed ? (
              <>
                <CheckCircle2 className="w-4 h-4" />
                Reinstall
              </>
            ) : (
              <>
                <Package className="w-4 h-4" />
                Install kit
              </>
            )}
          </Button>
          {isKitComingSoon(kit) && !kit.skeleton_installable ? (
            <p className="text-[10px] text-slate-600 max-w-[200px] text-right">
              This kit is not available yet. Check back for updates.
            </p>
          ) : isKitComingSoon(kit) && kit.skeleton_installable ? (
            <p className="text-[10px] text-slate-600 max-w-[200px] text-right">
              Skeleton install — connector stubs and container scaffolding only.
            </p>
          ) : !kit.bundle_ready ? (
            <p className="text-[10px] text-amber-700 max-w-[200px] text-right">
              Bundle not published yet. Run the publish script before installing.
            </p>
          ) : null}
        </div>
      </div>

      <Card className="py-4 gap-2 border-dashed">
        <CardContent className="px-4 flex items-start gap-2 text-xs text-muted-foreground">
          <FolderOpen className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>
            Install copies kit artifacts into the <strong>project root</strong> on the API host
            (e.g. <span className="font-mono">app/blocks/</span>,{' '}
            <span className="font-mono">app/containers/</span>). Target path is returned in the
            install response.
          </span>
        </CardContent>
      </Card>

      <Card className="py-4 gap-4">
        <CardHeader className="px-4 pb-0">
          <CardTitle className="text-sm">Blocks ({kit.blocks?.length ?? 0})</CardTitle>
        </CardHeader>
        <CardContent className="px-4">
          {kit.blocks?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {kit.blocks.map(block => (
                <span
                  key={block}
                  className="text-xs font-mono bg-gray-100 text-gray-700 px-2 py-1 rounded"
                >
                  {block}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No blocks listed</p>
          )}
        </CardContent>
      </Card>

      <Card className="py-4 gap-4">
        <CardHeader className="px-4 pb-0">
          <CardTitle className="text-sm">Artifacts ({kit.artifacts?.length ?? 0})</CardTitle>
          <CardDescription className="text-xs">Files copied on install</CardDescription>
        </CardHeader>
        <CardContent className="px-4">
          {kit.artifacts?.length ? (
            <ul className="text-xs font-mono space-y-1 max-h-48 overflow-y-auto">
              {kit.artifacts.map((item, i) => (
                <li key={`${item.src}-${i}`} className="text-gray-600 truncate">
                  {item.dest}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No artifacts</p>
          )}
        </CardContent>
      </Card>

      {sourceRepo ? (
        <Card className="py-4 gap-4">
          <CardHeader className="px-4 pb-0">
            <CardTitle className="text-sm">Source repository</CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            <a
              href={sourceRepo}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
            >
              {sourceRepo}
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
            {kit.source?.ref ? (
              <p className="text-xs text-muted-foreground mt-1">ref: {kit.source.ref}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <PreInstallChecklistModal
        kit={kit}
        open={checklistOpen}
        installing={installing}
        genericBlockStatus={genericBlockStatus}
        onClose={onCloseChecklist}
        onConfirm={onConfirmInstall}
      />
    </div>
  );
}

export default function Store() {
  const { kitId } = useParams<{ kitId?: string }>();
  const navigate = useNavigate();
  const [kits, setKits] = useState<ContainerKitSummary[]>([]);
  const [installedState, setInstalledState] = useState<
    Record<string, { version?: string; installed_at?: string; target_root?: string }>
  >({});
  const [selectedKit, setSelectedKit] = useState<ContainerKitDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<'browse' | 'installed'>('browse');
  const [availabilityFilter, setAvailabilityFilter] = useState<AvailabilityFilter>('all');
  const [checklistOpen, setChecklistOpen] = useState(false);
  const [installResult, setInstallResult] = useState<ContainerKitInstallResult | null>(null);
  const [genericBlockStatus, setGenericBlockStatus] = useState<Record<string, boolean>>({});

  const installedIds = useMemo(() => new Set(Object.keys(installedState)), [installedState]);

  const loadCatalog = useCallback(async () => {
    const data = await api.listStoreContainers();
    setKits(data.containers);
  }, []);

  const loadInstalled = useCallback(async () => {
    try {
      const data = await api.listInstalledContainers();
      setInstalledState(data.kits ?? {});
    } catch {
      setInstalledState({});
    }
  }, []);

  const loadGenericBlocks = useCallback(async () => {
    try {
      const data = await api.listBlocks();
      const names = new Set(data.blocks.map(b => b.name));
      const status: Record<string, boolean> = {};
      for (const block of REQUIRED_GENERIC_BLOCKS) {
        status[block] = names.has(block);
      }
      setGenericBlockStatus(status);
    } catch {
      const fallback: Record<string, boolean> = {};
      for (const block of REQUIRED_GENERIC_BLOCKS) {
        fallback[block] = true;
      }
      setGenericBlockStatus(fallback);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadCatalog(), loadInstalled(), loadGenericBlocks()]);
    } catch (err) {
      const { message } = describeError(err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [loadCatalog, loadInstalled, loadGenericBlocks]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!kitId) {
      setSelectedKit(null);
      setInstallResult(null);
      setChecklistOpen(false);
      return;
    }
    setDetailLoading(true);
    setError(null);
    setInstallResult(null);
    api
      .getStoreContainer(kitId)
      .then(setSelectedKit)
      .catch(err => {
        const { message } = describeError(err);
        setError(message);
        setSelectedKit(null);
      })
      .finally(() => setDetailLoading(false));
  }, [kitId]);

  const filteredKits = useMemo(() => {
    const q = search.toLowerCase().trim();
    return kits.filter(k => {
      if (!matchesAvailabilityFilter(k, availabilityFilter)) return false;
      if (!q) return true;
      return (
        k.name.toLowerCase().includes(q) ||
        k.id.toLowerCase().includes(q) ||
        (k.description || '').toLowerCase().includes(q) ||
        (k.tags || []).some(t => t.toLowerCase().includes(q))
      );
    });
  }, [kits, search, availabilityFilter]);

  const handleSelectKit = (id: string) => {
    navigate(`/store/${id}`);
  };

  const handleConfirmInstall = async () => {
    if (!selectedKit) return;
    setInstalling(true);
    try {
      const result = await api.installStoreContainer(selectedKit.id);
      setInstallResult(result);
      setChecklistOpen(false);
      toast.success(`Installed ${selectedKit.name}`, {
        description: `${result.copied?.length ?? 0} files copied`,
      });
      await loadInstalled();
    } catch (err) {
      const { message } = describeError(err);
      toast.error('Install failed', { description: message });
    } finally {
      setInstalling(false);
    }
  };

  const installedList = useMemo(
    () =>
      Object.entries(installedState).map(([id, record]) => {
        const meta = kits.find(k => k.id === id);
        return { id, record, meta };
      }),
    [installedState, kits]
  );

  const availabilityCounts = useMemo(
    () => ({
      all: kits.length,
      available: kits.filter(k => isKitInstallable(k)).length,
      coming_soon: kits.filter(k => isKitComingSoon(k)).length,
    }),
    [kits]
  );

  return (
    <div className="h-screen w-screen overflow-hidden bg-white flex flex-col">
      <AppHeader title="Block Store" subtitle="Container kits" />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 py-6">
          {kitId ? (
            detailLoading ? (
              <div className="flex items-center justify-center py-24 text-muted-foreground gap-2">
                <Loader2 className="w-5 h-5 animate-spin" />
                Loading kit…
              </div>
            ) : selectedKit ? (
              <KitDetailView
                kit={selectedKit}
                installing={installing}
                installed={installedIds.has(selectedKit.id)}
                installResult={installResult}
                genericBlockStatus={genericBlockStatus}
                checklistOpen={checklistOpen}
                onOpenChecklist={() => setChecklistOpen(true)}
                onCloseChecklist={() => setChecklistOpen(false)}
                onConfirmInstall={handleConfirmInstall}
                onDismissSuccess={() => setInstallResult(null)}
                onBack={() => navigate('/store')}
              />
            ) : (
              <div className="text-center py-24 text-muted-foreground">
                <XCircle className="w-8 h-8 mx-auto mb-2 text-red-400" />
                <p>Kit not found</p>
                <Button variant="link" asChild className="mt-2">
                  <Link to="/store">Back to catalog</Link>
                </Button>
              </div>
            )
          ) : (
            <>
              <div className="mb-6">
                <p className="text-sm text-muted-foreground">
                  Browse container kits published to the Cerebrum Block Store. Install a kit to copy
                  blocks, prompts, and domain modules into your instance.
                </p>
              </div>

              <Tabs value={tab} onValueChange={v => setTab(v as 'browse' | 'installed')}>
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
                  <TabsList>
                    <TabsTrigger value="browse" className="gap-1.5">
                      <Box className="w-3.5 h-3.5" />
                      Browse
                    </TabsTrigger>
                    <TabsTrigger value="installed" className="gap-1.5">
                      <Package className="w-3.5 h-3.5" />
                      Installed ({installedList.length})
                    </TabsTrigger>
                  </TabsList>
                  {tab === 'browse' ? (
                    <div className="relative w-full sm:w-64">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                      <Input
                        placeholder="Search kits…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        className="pl-8 h-8 text-sm"
                      />
                    </div>
                  ) : null}
                </div>

                {error ? (
                  <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    {error}
                  </div>
                ) : null}

                <TabsContent value="browse" className="mt-0">
                  <div className="flex items-center gap-1 mb-4">
                    <Tabs
                      value={availabilityFilter}
                      onValueChange={v => setAvailabilityFilter(v as AvailabilityFilter)}
                    >
                      <TabsList className="h-8">
                        <TabsTrigger value="all" className="text-xs px-2.5 h-7">
                          All ({availabilityCounts.all})
                        </TabsTrigger>
                        <TabsTrigger value="available" className="text-xs px-2.5 h-7 gap-1">
                          <CheckCircle2 className="w-3 h-3" />
                          Available ({availabilityCounts.available})
                        </TabsTrigger>
                        <TabsTrigger value="coming_soon" className="text-xs px-2.5 h-7 gap-1">
                          <Clock className="w-3 h-3" />
                          Coming Soon ({availabilityCounts.coming_soon})
                        </TabsTrigger>
                      </TabsList>
                    </Tabs>
                  </div>

                  {loading ? (
                    <div className="flex items-center justify-center py-24 text-muted-foreground gap-2">
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Loading catalog…
                    </div>
                  ) : filteredKits.length === 0 ? (
                    <div className="text-center py-24 text-muted-foreground">
                      <Box className="w-8 h-8 mx-auto mb-2 opacity-40" />
                      <p>
                        {kits.length === 0
                          ? 'No kits in catalog'
                          : 'No kits match your search or filter'}
                      </p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {filteredKits.map(kit => (
                        <KitCard
                          key={kit.id}
                          kit={kit}
                          installed={installedIds.has(kit.id)}
                          onSelect={handleSelectKit}
                        />
                      ))}
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="installed" className="mt-0">
                  {installedList.length === 0 ? (
                    <div className="text-center py-24 text-muted-foreground">
                      <Package className="w-8 h-8 mx-auto mb-2 opacity-40" />
                      <p>No kits installed yet</p>
                      <Button variant="link" onClick={() => setTab('browse')} className="mt-2">
                        Browse the catalog
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {installedList.map(({ id, record, meta }) => (
                        <Card key={id} className="py-4 gap-2">
                          <CardContent className="px-4 flex items-center justify-between gap-4">
                            <div className="min-w-0">
                              <p className="font-medium text-sm truncate">{meta?.name ?? id}</p>
                              <p className="text-xs text-muted-foreground">
                                v{record.version ?? meta?.version ?? '?'}
                                {record.installed_at
                                  ? ` · installed ${new Date(record.installed_at).toLocaleString()}`
                                  : ''}
                              </p>
                              {record.target_root ? (
                                <p className="text-[10px] text-gray-400 font-mono truncate mt-0.5">
                                  {record.target_root}
                                </p>
                              ) : null}
                            </div>
                            <Button variant="outline" size="sm" onClick={() => handleSelectKit(id)}>
                              View
                            </Button>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
