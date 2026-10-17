export type ParamFieldType = 'text' | 'number' | 'boolean' | 'select' | 'json' | 'file';

export interface ParamField {
  name: string;
  type: ParamFieldType;
  label?: string;
  default?: unknown;
  options?: string[];
}

export interface UniversalUiSchema {
  input?: {
    type?: string;
    placeholder?: string;
    accept?: string[] | null;
    multiline?: boolean;
  };
  output?: {
    type?: string;
    fields?: Array<{ name: string; type?: string; label?: string }>;
  };
  params?: ParamField[];
  quick_actions?: Array<{ icon?: string; label?: string; prompt?: string }>;
}

function widgetToType(widget: string): ParamFieldType {
  switch (widget) {
    case 'toggle':
      return 'boolean';
    case 'number':
      return 'number';
    case 'json':
      return 'json';
    case 'select':
      return 'select';
    case 'file':
      return 'file';
    default:
      return 'text';
  }
}

/** Normalize inline UniversalBlock ui_schema or registry manifest widgets. */
export function parseUiSchema(raw: unknown): UniversalUiSchema | null {
  if (!raw || typeof raw !== 'object') return null;
  const schema = raw as UniversalUiSchema & { params?: unknown };

  if (Array.isArray(schema)) {
    const widgets = schema as Array<{ name?: string; widget?: string; label?: string; options?: string[] }>;
    return {
      input: { type: 'json', placeholder: 'Block input' },
      params: widgets
        .filter(w => w.name && w.name !== 'input')
        .map(w => ({
          name: w.name!,
          type: widgetToType(w.widget || 'text'),
          label: w.label,
          options: w.options,
        })),
    };
  }

  if (Array.isArray(schema.params)) {
    return schema as UniversalUiSchema;
  }

  return schema as UniversalUiSchema;
}

export function extractParamFields(uiSchema: unknown): ParamField[] {
  const parsed = parseUiSchema(uiSchema);
  if (!parsed?.params?.length) return [];
  return parsed.params.filter((field): field is ParamField => !!field?.name);
}

export function defaultParamsFromFields(fields: ParamField[]): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.default !== undefined) {
      params[field.name] = field.default;
      continue;
    }
    switch (field.type) {
      case 'boolean':
        params[field.name] = false;
        break;
      case 'number':
        params[field.name] = 0;
        break;
      case 'select':
        params[field.name] = field.options?.[0] ?? '';
        break;
      case 'json':
        params[field.name] = {};
        break;
      default:
        params[field.name] = '';
    }
  }
  return params;
}

export function mergeParamsWithSchema(
  existing: Record<string, unknown> | undefined,
  fields: ParamField[]
): Record<string, unknown> {
  const defaults = defaultParamsFromFields(fields);
  return { ...defaults, ...(existing || {}) };
}
