export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'error';
  content: string;
  timestamp: number;
  attachments?: FileAttachment[];
}

export interface FileAttachment {
  name: string;
  type: string;
  size: number;
  content?: string;
  url?: string;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  active?: boolean;
  files?: FileNode[];
  source?: string;
}

export interface DriveSource {
  id: string;
  name: string;
  icon: string;
  connected: boolean;
  type: 'local' | 'server' | 'google' | 'onedrive' | 'android' | 'dropbox';
  files?: FileNode[];
  fileObjects?: File[];
}

export interface FileNode {
  id: string;
  name: string;
  type: 'file' | 'folder';
  children?: FileNode[];
  expanded?: boolean;
  selected?: boolean;
  path?: string;
}

export interface ConstructionPanel {
  id: string;
  title: string;
  visible: boolean;
  data?: unknown;
}

// Raw shapes returned by the backend construction pipeline. Most fields are
// optional because each block emits a slightly different superset; the mapper
// reads whichever names are present.

export interface RawPanel<T = unknown> {
  type: string;
  data?: T;
  line_items?: unknown[];
}

export interface RawProcurementItem {
  id?: string | number;
  item?: string;
  name?: string;
  quantity?: number;
  unit?: string;
  lead_time_weeks?: number;
  lead_time_days?: number;
  lead_time?: number;
  priority?: string;
  critical?: boolean;
  supplier?: string;
  supplier_type?: string;
  status?: string;
}

export interface RawRisk {
  id?: string | number;
  description?: string;
  risk?: string;
  item?: string;
  severity?: string;
  level?: string;
  category?: string;
  type?: string;
  mitigation?: string;
  recommendation?: string;
}

export interface RawSubmittal {
  id?: string | number;
  item?: string;
  name?: string;
  description?: string;
  status?: string;
  category?: string;
  type?: string;
}

export interface RawScheduleActivity {
  id?: string | number;
  task?: string;
  name?: string;
  activity_name?: string;
  start?: string;
  start_date?: string;
  end?: string;
  finish?: string;
  end_date?: string;
  duration?: number;
  duration_days?: number;
  progress?: number;
  percent_complete?: number;
  status?: string;
}

export interface RawContractClause {
  id?: string | number;
  title?: string;
  name?: string;
  content?: string;
  text?: string;
  section?: string;
}

export interface RawDriveFile {
  name?: string;
  filename?: string;
  path?: string;
  file_path?: string;
  type?: string;
  is_dir?: boolean;
  is_folder?: boolean;
}

export interface ConstructionApiResult {
  status?: string;
  panels?: RawPanel[];
  next_actions?: NextAction[];
  chat_context?: string;
  file_name?: string;
  result?: ConstructionApiResult;

  // Action-specific fields the SPA consumes
  procurement_list?: RawProcurementItem[];
  items?: RawProcurementItem[];
  total_procurement_cost?: number;
  critical_long_lead_items?: number;
  message?: string;
  summary?: string;
  text?: string;
  response?: string;
  certificate_summary?: string;
  overall_progress?: { actual_percent?: number };
}

export interface DocumentInfo {
  type: string;
  title: string;
  project: string;
  pages: number;
  author?: string;
  date?: string;
}

export interface QuantityItem {
  item: string;
  quantity: number;
  unit: string;
}

export interface CostEstimate {
  subtotal: number;
  overhead: number;
  contingency: number;
  total: number;
  currency: string;
}

export interface Risk {
  id: string;
  description: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  category: string;
  mitigation?: string;
}

export interface Submittal {
  id: string;
  item: string;
  status: 'APPROVED' | 'PENDING' | 'REJECTED' | 'REQUIRED';
  category: string;
}

export interface ScheduleItem {
  id: string;
  task: string;
  start: string;
  end: string;
  duration: number;
  progress: number;
  status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'DELAYED';
}

export interface ContractClause {
  id: string;
  title: string;
  content: string;
  section: string;
}

export interface ProcurementItem {
  id: string;
  item: string;
  quantity: number;
  unit: string;
  leadTime: number;
  critical: boolean;
  supplier?: string;
  status: string;
}

export interface ProcessingState {
  active: boolean;
  stage: string;
  progress: number;
}

export interface PipelineCtx {
  file_path: string;
  extracted_text: string;
  quantities: Record<string, unknown>;
  costLineItems: unknown[];
  fileName: string;
}

export interface NextAction {
  action: string;
  label: string;
  reason?: string;
}

export type Theme = 'light' | 'dark';

export type PanelType =
  | 'documentInfo'
  | 'quantities'
  | 'costEstimate'
  | 'risks'
  | 'submittals'
  | 'schedule'
  | 'contract'
  | 'procurement';
