import type {
  Message,
  DocumentInfo,
  QuantityItem,
  CostEstimate,
  Risk,
  Submittal,
  ScheduleItem,
  ContractClause,
  ProcurementItem,
  PipelineCtx,
  FileNode,
  RawPanel,
  RawRisk,
  RawSubmittal,
  RawScheduleActivity,
  RawContractClause,
  RawProcurementItem,
  RawDriveFile,
  ConstructionApiResult,
} from '@/types';

const isLocalHost =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (isLocalHost ? 'http://localhost:8000' : 'https://cerebrum-platform-api.onrender.com');

// Public-tier key injected at build time. SPAs cannot keep secrets — this key
// must be scoped to client-safe operations on the server. Never inline a master key.
const API_KEY = import.meta.env.VITE_API_KEY ?? (isLocalHost ? 'cb_dev_key' : '');

export interface BlockMeta {
  name: string;
  version: string;
  description: string;
  layer: number;
  tags: string[];
  requires: string[];
  ui_schema: Record<string, unknown>;
}

export interface ChainStep {
  block: string;
  params: Record<string, unknown>;
  label?: string;
  input_mapping?: Record<string, string>;
}

export interface ChainResult {
  success: boolean;
  status: string;
  steps_executed: number;
  final_output?: unknown;
  results: Array<Record<string, unknown>>;
  error?: string;
  validation_errors?: unknown[];
}

export interface ContainerKitSummary {
  id: string;
  name: string;
  version: string;
  description?: string;
  tags?: string[];
  author?: string;
  price_cents?: number;
  status?: string;
  coming_soon?: boolean;
  bundle_ready?: boolean;
  skeleton_ready?: boolean;
  skeleton_installable?: boolean;
  installable?: boolean;
  source?: ContainerKitSource;
  blocks?: string[];
}

export interface ContainerKitSource {
  repo?: string;
  ref?: string;
  publish_script?: string;
}

export interface ContainerKitArtifact {
  src: string;
  dest: string;
}

export interface ContainerKitDetail extends ContainerKitSummary {
  container?: {
    class?: string;
    default_chat_prompt?: string;
  };
  prompts?: string[];
  data?: string[];
  core_modules?: string[];
  artifacts?: ContainerKitArtifact[];
  install_requires?: Record<string, string>;
}

export interface ContainerKitInstallResult {
  status: string;
  kit_id: string;
  version?: string;
  target_root?: string;
  copied?: string[];
  skipped?: Array<{ dest: string; reason: string }>;
  installed_at?: string;
}

export interface InstalledContainerKits {
  kits: Record<
    string,
    {
      version?: string;
      installed_at?: string;
      target_root?: string;
      files?: string[];
    }
  >;
}

export type ApiErrorKind =
  | 'network'           // status 0 — fetch threw / CORS-stripped failure
  | 'auth'              // 401
  | 'forbidden'         // 403
  | 'not-found'         // 404
  | 'payload-too-large' // 413
  | 'rate-limited'      // 429
  | 'server-down'       // 502/503/504 (after retries exhausted)
  | 'server-error'      // 5xx other
  | 'client-error'      // 4xx other
  | 'unknown';

export class ApiError extends Error {
  status: number;
  kind: ApiErrorKind;
  constructor(status: number, message: string, kind?: ApiErrorKind) {
    super(message);
    this.status = status;
    this.kind = kind ?? classifyStatus(status);
  }
}

function classifyStatus(status: number): ApiErrorKind {
  if (status === 0) return 'network';
  if (status === 401) return 'auth';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not-found';
  if (status === 413) return 'payload-too-large';
  if (status === 429) return 'rate-limited';
  if (status === 502 || status === 503 || status === 504) return 'server-down';
  if (status >= 500) return 'server-error';
  if (status >= 400) return 'client-error';
  return 'unknown';
}

/** Stable, user-facing message for each error kind. UI components map the
 *  tag directly to a banner / toast so we don't render raw API error text. */
export function describeError(err: unknown): { kind: ApiErrorKind; message: string } {
  if (err instanceof ApiError) {
    const messages: Record<ApiErrorKind, string> = {
      'network': 'Server unreachable. Check your connection and try again.',
      'auth': 'Session expired or invalid API key. Please sign in again.',
      'forbidden': 'You don\'t have permission for that action.',
      'not-found': 'Endpoint not found. The feature may be unavailable.',
      'payload-too-large': 'File is too large. Try a smaller file.',
      'rate-limited': 'Too many requests — slow down for a moment.',
      'server-down': 'Server is restarting. Please retry in a minute.',
      'server-error': 'The server encountered an error. Please try again.',
      'client-error': err.message || 'Request rejected.',
      'unknown': err.message || 'An unexpected error occurred.',
    };
    return { kind: err.kind, message: messages[err.kind] };
  }
  return { kind: 'unknown', message: err instanceof Error ? err.message : 'An unexpected error occurred.' };
}

// Render's upstream returns 502/503 during deploy swaps, cold starts, or when
// the worker is briefly unhealthy. A full Render deploy swap takes 2–3 minutes;
// the previous 5-second retry budget couldn't bridge that. Stretched out to
// ~3 minutes total so a user-initiated upload survives a redeploy window
// instead of the SPA giving up after 5s.
//
// 4xx aren't retried — those are real client problems.
const _RETRYABLE_STATUSES = new Set([502, 503, 504]);
const _MAX_RETRIES = 6;
const _RETRY_BACKOFF_MS = [500, 1500, 4000, 10000, 30000, 60000];  // ~106s total

// Methods we'll auto-retry on transient 5xx. Mutating verbs (POST/PUT/PATCH/
// DELETE) are *not* on this list — without an Idempotency-Key header,
// retrying them risks double-issuing things like payment_certificate.
// /chat and /v1/execute are exceptions: chat is replayable (the model just
// re-runs) and /v1/execute is the only way the SPA reaches container
// actions, so we accept the (small) double-execute risk in exchange for
// surviving Render redeploys mid-conversation.
const _RETRY_SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const _RETRY_ALLOWLISTED_PATHS = new Set([
  '/chat',
  '/v1/execute',
  '/health',
]);

function _shouldRetry(method: string, path: string): boolean {
  if (_RETRY_SAFE_METHODS.has(method.toUpperCase())) return true;
  return _RETRY_ALLOWLISTED_PATHS.has(path);
}

async function fetchApi(path: string, options?: RequestInit): Promise<unknown> {
  const url = `${API_BASE}${path}`;
  const method = (options?.method || 'GET').toUpperCase();
  const retryable = _shouldRetry(method, path);
  let lastError: ApiError | null = null;

  const maxAttempts = retryable ? _MAX_RETRIES : 0;

  for (let attempt = 0; attempt <= maxAttempts; attempt++) {
    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${API_KEY}`,
          ...options?.headers,
        },
      });
    } catch (e) {
      // Network error (often the CORS-stripped 502 manifests this way).
      lastError = new ApiError(0, e instanceof Error ? e.message : 'Network error');
      if (retryable && attempt < maxAttempts) {
        await new Promise(r => setTimeout(r, _RETRY_BACKOFF_MS[attempt]));
        continue;
      }
      throw lastError;
    }

    if (response.ok) {
      return response.json();
    }

    if (retryable && _RETRYABLE_STATUSES.has(response.status) && attempt < maxAttempts) {
      await new Promise(r => setTimeout(r, _RETRY_BACKOFF_MS[attempt]));
      continue;
    }

    const errorText = await response.text();
    throw new ApiError(response.status, errorText || `HTTP ${response.status}`);
  }

  throw lastError ?? new ApiError(0, 'fetchApi: retry loop exhausted');
}

// Unwrap the optional `{ result: ... }` envelope some endpoints use.
function unwrapResult<T = ConstructionApiResult>(raw: unknown): T {
  const r = raw as { result?: T } | T;
  return ((r as { result?: T })?.result ?? r) as T;
}

export const api = {
  // Chat — sends last message with up to 6 prior turns for multi-turn context
  async sendMessage(messages: Message[]): Promise<{
    text: string;
    response?: string;
    fallback?: boolean;
    fallback_reason?: string;
    provider?: string;
  }> {
    const lastUser = [...messages].reverse().find(m => m.role === 'user');
    if (!lastUser) return { text: '' };

    // Build conversation history from prior turns (exclude the current message)
    const priorTurns = messages
      .filter(m => m.id !== lastUser.id && (m.role === 'user' || m.role === 'assistant'))
      .slice(-6);

    let message = lastUser.content || '';
    if (priorTurns.length > 0) {
      const historyText = priorTurns
        .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
        .join('\n');
      message = `Previous conversation:\n${historyText}\n\nCurrent message: ${message}`;
    }

    return fetchApi('/chat', {
      method: 'POST',
      body: JSON.stringify({ message, model: 'deepseek-chat', stream: false }),
    }) as Promise<{
      text: string;
      response?: string;
      fallback?: boolean;
      fallback_reason?: string;
      provider?: string;
    }>;
  },

  // Upload — multipart; returns file_path (absolute server path)
  // Same 502/503 retry policy as fetchApi (deploy windows hit upload too).
  async uploadFile(file: File): Promise<{ file_path: string; filename: string; url: string }> {
    let lastError: ApiError | null = null;
    for (let attempt = 0; attempt <= _MAX_RETRIES; attempt++) {
      const formData = new FormData();
      formData.append('file', file);

      let response: Response;
      try {
        response = await fetch(`${API_BASE}/upload`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${API_KEY}` },
          body: formData,
        });
      } catch (e) {
        lastError = new ApiError(0, e instanceof Error ? e.message : 'Network error');
        if (attempt < _MAX_RETRIES) {
          await new Promise(r => setTimeout(r, _RETRY_BACKOFF_MS[attempt]));
          continue;
        }
        throw lastError;
      }

      if (response.ok) return response.json();
      if (_RETRYABLE_STATUSES.has(response.status) && attempt < _MAX_RETRIES) {
        await new Promise(r => setTimeout(r, _RETRY_BACKOFF_MS[attempt]));
        continue;
      }
      const error = await response.text();
      throw new ApiError(response.status, error);
    }
    throw lastError ?? new ApiError(0, 'uploadFile: retry loop exhausted');
  },

  // Extract text from a PDF or image via the pdf/ocr block
  async extractText(filePath: string, isImage = false): Promise<string> {
    const block = isImage ? 'ocr' : 'pdf';
    const raw = await fetchApi('/v1/execute', {
      method: 'POST',
      body: JSON.stringify({
        block,
        input: { file_path: filePath },
        params: {},
      }),
    });
    const inner = unwrapResult<{ text?: string; content?: string }>(raw);
    return inner.text || inner.content || '';
  },

  // Run construction auto_pipeline — action must be in params, NOT in input
  async analyzeConstruction(filePath: string, extractedText: string): Promise<ConstructionApiResult> {
    const raw = await fetchApi('/v1/execute', {
      method: 'POST',
      body: JSON.stringify({
        block: 'construction',
        input: { file_path: filePath, extracted_text: extractedText },
        params: { action: 'auto_pipeline', doc_type: 'auto' },
      }),
    });
    return unwrapResult<ConstructionApiResult>(raw);
  },

  // Trigger a subsequent construction action with pipeline context
  async runAction(action: string, ctx: Omit<PipelineCtx, 'fileName'>): Promise<ConstructionApiResult> {
    const raw = await fetchApi('/v1/execute', {
      method: 'POST',
      body: JSON.stringify({
        block: 'construction',
        input: {
          file_path: ctx.file_path,
          extracted_text: ctx.extracted_text,
          quantities: ctx.quantities || {},
          line_items: ctx.costLineItems || [],
        },
        params: { action },
      }),
    });
    return unwrapResult<ConstructionApiResult>(raw);
  },

  // Drive — local needs no API call (native file picker); server uses local_drive block
  async connectDrive(type: string): Promise<{ success: boolean; files?: FileNode[] }> {
    if (type === 'local') {
      return { success: true, files: [] };
    }
    if (type === 'server') {
      const raw = await fetchApi('/v1/execute', {
        method: 'POST',
        body: JSON.stringify({
          block: 'local_drive',
          input: null,
          params: { operation: 'list', folder_path: './' },
        }),
      });
      const inner = unwrapResult<{ files?: (RawDriveFile | string)[]; items?: (RawDriveFile | string)[] }>(raw);
      const rawFiles: (RawDriveFile | string)[] = inner.files || inner.items || [];
      const fileNodes: FileNode[] = rawFiles.map((f, i) => {
        if (typeof f === 'string') {
          return { id: `server-file-${i}`, name: f, type: 'file', path: f };
        }
        const name = f.name || f.filename || '';
        const isDir = f.type === 'directory' || f.is_dir === true || f.is_folder === true;
        const path = f.path || f.file_path || f.name || '';
        return { id: `server-file-${i}`, name, type: isDir ? 'folder' : 'file', path };
      });
      return { success: true, files: fileNodes };
    }
    // Cloud drives (google / onedrive / dropbox / android) are not yet
    // wired to a backend route. The DriveConnectModal currently disables
    // these entries, so this branch is only reachable if a future change
    // enables them without adding the corresponding backend handler.
    // Fail loudly so the regression is obvious instead of silently 404ing
    // through fetchApi.
    throw new ApiError(
      501,
      `Cloud drive '${type}' is not yet supported. Use 'local' or 'server'.`,
      'not-found',
    );
  },

  // Generic one-off block call (used for ZVec, etc.)
  async runBlock(block: string, input: unknown, params: Record<string, unknown>): Promise<unknown> {
    const raw = await fetchApi('/v1/execute', {
      method: 'POST',
      body: JSON.stringify({ block, input, params }),
    });
    return unwrapResult<unknown>(raw);
  },

  // Group a drive's files into projects via construction.discover_projects
  // (which uses zvec char-level TF-IDF similarity + path-prefix clustering).
  async discoverProjects(
    files: Array<{ name: string; path?: string }>,
  ): Promise<{
    projects: Array<{ id: string; name: string; files: Array<{ name: string; path?: string }>; file_count: number; source?: string }>;
    uncategorized: Array<{ name: string; path?: string }>;
    total_files: number;
    total_projects: number;
    method?: string;
  }> {
    const raw = await fetchApi('/v1/execute', {
      method: 'POST',
      body: JSON.stringify({
        block: 'construction',
        input: { files },
        params: { action: 'discover_projects' },
      }),
    });
    return unwrapResult(raw) as Awaited<ReturnType<typeof api.discoverProjects>>;
  },

  // List all available blocks
  async listBlocks(): Promise<{ blocks: BlockMeta[]; total: number }> {
    return fetchApi('/blocks') as Promise<{ blocks: BlockMeta[]; total: number }>;
  },

  // Execute a chain of blocks
  async executeChain(steps: ChainStep[], initialInput?: unknown): Promise<ChainResult> {
    return fetchApi('/chain', {
      method: 'POST',
      body: JSON.stringify({
        steps,
        initial_input: initialInput ?? {},
        fail_fast: true,
        continue_on_error: false,
      }),
    }) as Promise<ChainResult>;
  },

  // Health check
  async health(): Promise<{ status: string }> {
    return fetchApi('/health') as Promise<{ status: string }>;
  },

  // Block Store — container kits
  async listStoreContainers(): Promise<{ containers: ContainerKitSummary[]; total: number }> {
    return fetchApi('/store/containers') as Promise<{
      containers: ContainerKitSummary[];
      total: number;
    }>;
  },

  async getStoreContainer(kitId: string): Promise<ContainerKitDetail> {
    return fetchApi(`/store/containers/${encodeURIComponent(kitId)}`) as Promise<ContainerKitDetail>;
  },

  async installStoreContainer(
    kitId: string,
    options?: { force?: boolean }
  ): Promise<ContainerKitInstallResult> {
    return fetchApi(`/store/containers/${encodeURIComponent(kitId)}/install`, {
      method: 'POST',
      body: JSON.stringify({ force: options?.force ?? false }),
    }) as Promise<ContainerKitInstallResult>;
  },

  async listInstalledContainers(): Promise<InstalledContainerKits> {
    return fetchApi('/store/containers/installed') as Promise<InstalledContainerKits>;
  },
};

interface RawDocumentInfoData {
  doc_type?: string;
  type?: string;
  title?: string;
  project?: string;
  pages?: number;
  total_pages?: number;
  author?: string;
  drawn_by?: string;
  date?: string;
}

interface RawQuantityValue {
  qty?: number;
  quantity?: number;
  total?: number;
  unit?: string;
}

interface RawCostEstimateData {
  subtotal?: number;
  total?: number;
  overhead?: number;
  contingency?: number;
  currency?: string;
}

interface RawContractObligation {
  type?: string;
  text?: string;
  category?: string;
  priority?: string;
}

interface RawContractData {
  extracted_clauses?: Record<string, { found?: boolean; examples?: string[] }>;
  clauses?: RawContractClause[];
  key_obligations?: RawContractObligation[];
  summary?: string;
  contract_type?: string;
}

// Map auto_pipeline panels array response to typed panel state
export function mapConstructionResult(result: ConstructionApiResult | null | undefined): {
  documentInfo: DocumentInfo | null;
  quantities: QuantityItem[];
  costEstimate: CostEstimate | null;
  risks: Risk[];
  submittals: Submittal[];
  schedule: ScheduleItem[];
  contract: ContractClause[];
  procurement: ProcurementItem[];
} {
  const empty = {
    documentInfo: null, quantities: [], costEstimate: null,
    risks: [], submittals: [], schedule: [], contract: [], procurement: [],
  };

  if (!result || result.status === 'error') return empty;

  const panels: RawPanel[] = result.panels || [];
  const getPanel = <T = unknown>(type: string): RawPanel<T> | undefined =>
    panels.find(p => p.type === type) as RawPanel<T> | undefined;

  const docPanel = getPanel<RawDocumentInfoData>('document_info');
  const qPanel = getPanel<Record<string, number | RawQuantityValue> | RawQuantityValue[]>('quantities');
  const costPanel = getPanel<RawCostEstimateData>('cost_estimate');
  const riskPanel = getPanel<RawRisk[]>('risks');
  const submittalPanel = getPanel<RawSubmittal[] | { submittals?: RawSubmittal[] }>('submittals');
  const schedulePanel = getPanel<RawScheduleActivity[] | { activities?: RawScheduleActivity[] }>('schedule');
  const contractPanel = getPanel<RawContractData | RawContractClause[]>('contract');
  const procurementPanel = getPanel<RawProcurementItem[] | { procurement_list?: RawProcurementItem[] }>('procurement');

  const documentInfo: DocumentInfo | null = docPanel?.data
    ? {
        type: docPanel.data.doc_type || docPanel.data.type || 'Document',
        title: docPanel.data.title || result.file_name?.replace(/\.[^/.]+$/, '') || 'Document',
        project: docPanel.data.project || 'Unknown Project',
        pages: docPanel.data.pages || docPanel.data.total_pages || 1,
        author: docPanel.data.author || docPanel.data.drawn_by || 'Unknown',
        date: docPanel.data.date || new Date().toISOString().split('T')[0],
      }
    : null;

  const quantities: QuantityItem[] = (() => {
    const q = qPanel?.data;
    if (!q) return [];
    if (Array.isArray(q)) {
      return q.map(v => ({
        item: '',
        quantity: v.qty ?? v.quantity ?? v.total ?? 0,
        unit: v.unit ?? 'units',
      }));
    }
    return Object.entries(q).map(([item, data]) => ({
      item: item.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      quantity: typeof data === 'object' ? data.qty ?? data.quantity ?? data.total ?? 0 : Number(data),
      unit: typeof data === 'object' ? data.unit ?? 'units' : 'units',
    }));
  })();

  const costEstimate: CostEstimate | null = costPanel?.data
    ? {
        subtotal: costPanel.data.subtotal ?? costPanel.data.total ?? 0,
        overhead: costPanel.data.overhead ?? 0,
        contingency: costPanel.data.contingency ?? 0,
        total: costPanel.data.total ?? costPanel.data.subtotal ?? 0,
        currency: costPanel.data.currency ?? '$',
      }
    : null;

  // M8: normalise severity to the UI enum. Anything we don't recognise
  // (backends sometimes emit 'severe', 'minor', 'urgent') maps to MEDIUM
  // so the badge still styles consistently instead of falling back to
  // the muted default.
  const _normaliseSeverity = (raw: unknown): Risk['severity'] => {
    const v = String(raw || '').toUpperCase().trim();
    if (v === 'CRITICAL' || v === 'SEVERE' || v === 'URGENT') return 'CRITICAL';
    if (v === 'HIGH') return 'HIGH';
    if (v === 'LOW' || v === 'MINOR') return 'LOW';
    return 'MEDIUM';
  };
  const risks: Risk[] = (riskPanel?.data || []).map((r, i) => ({
    id: String(r.id ?? i + 1),
    description: r.description || r.risk || r.item || 'Unknown risk',
    severity: _normaliseSeverity(r.severity || r.level),
    category: r.category || r.type || 'General',
    mitigation: r.mitigation || r.recommendation || '',
  }));

  return {
    documentInfo,
    quantities,
    costEstimate,
    risks,
    submittals: (() => {
      const d = submittalPanel?.data;
      const raw: RawSubmittal[] = Array.isArray(d)
        ? d
        : (Array.isArray(d?.submittals) ? d.submittals : []);
      return raw.map((s, i) => ({
        id: String(s.id ?? i + 1),
        item: s.item || s.name || s.description || 'Unknown',
        status: ((s.status || 'PENDING').toUpperCase()) as Submittal['status'],
        category: s.category || s.type || 'General',
      }));
    })(),
    schedule: (() => {
      const d = schedulePanel?.data as
        | RawScheduleActivity[]
        | {
            activities?: RawScheduleActivity[];
            detailed_activities?: RawScheduleActivity[];
            critical_path?: { activities?: RawScheduleActivity[] };
          }
        | undefined;
      const raw: RawScheduleActivity[] = Array.isArray(d)
        ? d
        : (
            (d && Array.isArray(d.activities) && d.activities) ||
            (d && Array.isArray(d.detailed_activities) && d.detailed_activities) ||
            (d && d.critical_path && Array.isArray(d.critical_path.activities) && d.critical_path.activities) ||
            []
          );
      return raw.map((a, i) => {
        const progress = a.progress ?? a.percent_complete ?? 0;
        return {
          id: String(a.id ?? i + 1),
          task: a.task || a.name || a.activity_name || 'Unknown',
          start: a.start || a.start_date || '',
          end: a.end || a.finish || a.end_date || '',
          duration: a.duration ?? a.duration_days ?? 0,
          progress,
          status: (a.status || (progress >= 100 ? 'COMPLETED' : progress > 0 ? 'IN_PROGRESS' : 'NOT_STARTED')) as ScheduleItem['status'],
        };
      });
    })(),
    contract: (() => {
      const d = contractPanel?.data;
      const out: ContractClause[] = [];

      // Section 1: extracted_clauses (the headline panel rows)
      if (d && !Array.isArray(d) && d.extracted_clauses && typeof d.extracted_clauses === 'object') {
        Object.entries(d.extracted_clauses).forEach(([key, val], i) => {
          out.push({
            id: `clause-${i + 1}`,
            title: key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
            content: val?.examples?.[0] || '',
            section: val?.found ? 'Found' : 'Not Found',
          });
        });
      } else {
        const raw: RawContractClause[] = Array.isArray(d)
          ? d
          : (d && Array.isArray(d.clauses) ? d.clauses : []);
        raw.forEach((c, i) => {
          out.push({
            id: String(c.id ?? `clause-${i + 1}`),
            title: c.title || c.name || 'Unknown',
            content: c.content || c.text || '',
            section: c.section || '',
          });
        });
      }

      // M5: surface key_obligations as their own clauses so the user
      // sees them in the contract panel rather than just the clause-found
      // list. Tagged with section "Obligation" for visual grouping.
      if (d && !Array.isArray(d) && Array.isArray(d.key_obligations)) {
        d.key_obligations.slice(0, 20).forEach((o, i) => {
          out.push({
            id: `obligation-${i + 1}`,
            title: (o.type || 'Obligation').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
            content: o.text || '',
            section: o.priority ? `Obligation · ${o.priority}` : 'Obligation',
          });
        });
      }

      // M9: surface the human summary as a leading clause-shaped row so
      // users see the big-picture verdict above the line items.
      if (d && !Array.isArray(d) && d.summary) {
        out.unshift({
          id: 'summary',
          title: d.contract_type
            ? `Summary · ${String(d.contract_type).replace(/_/g, ' ')}`
            : 'Summary',
          content: d.summary,
          section: 'Overview',
        });
      }

      return out;
    })(),
    procurement: (() => {
      const d = procurementPanel?.data;
      const raw: RawProcurementItem[] = Array.isArray(d)
        ? d
        : (Array.isArray(d?.procurement_list) ? d.procurement_list : []);
      return raw.map((item, i) => ({
        id: String(item.id ?? i + 1),
        item: item.item || item.name || 'Unknown',
        quantity: item.quantity ?? 0,
        unit: item.unit || 'units',
        leadTime: item.lead_time_weeks ?? item.lead_time_days ?? item.lead_time ?? 0,
        critical: item.priority === 'critical' || item.critical === true,
        supplier: item.supplier_type || item.supplier || undefined,
        status: item.status || 'PENDING',
      }));
    })(),
  };
}
