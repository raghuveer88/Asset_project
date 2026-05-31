export interface Property {
  property_code: string;
  property_name?: string | null;
  official_property_name?: string | null;
  address?: string | null;
  website_url?: string | null;
  scrape_enabled: boolean;
  match_confidence?: string | null;
  has_rent_roll_snapshots: boolean;
  has_website_pages: boolean;
  rent_roll_snapshot_count: number;
  website_page_count: number;
}

export interface Diagnostics {
  db_connected: boolean;
  property_count: number;
  properties_count?: number;
  snapshot_count?: number;
  snapshots_count?: number;
  rent_roll_row_count: number;
  rent_roll_rows_count?: number;
  summary_group_count?: number;
  summary_groups_count?: number;
  charge_summary_count?: number;
  charge_summaries_count?: number;
  future_resident_count?: number;
  future_residents_count?: number;
  website_page_count: number;
  website_pages_count?: number;
  chroma_chunks_count?: number | null;
  chroma_collection_status: Record<string, unknown>;
  available_models: string[];
  embedding_model: string;
}

export interface ResponseComponent {
  type: 'kpi_cards' | 'table' | 'bar_chart' | 'line_chart';
  title: string;
  data?: Record<string, unknown>[];
  columns?: string[];
  rows?: Record<string, unknown>[] | unknown[][];
  x_key?: string;
  y_key?: string;
}

export interface Source {
  title?: string | null;
  url?: string | null;
  snippet?: string | null;
}

export interface Followup {
  label: string;
  question: string;
  route_hint?: string | null;
}

export interface ChatResponse {
  answer_markdown: string;
  components: ResponseComponent[];
  sources: Source[];
  followups: Followup[];
  metadata: {
    property_code: string;
    model: string;
    tools_used: string[];
    route: string;
  };
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  response?: ChatResponse;
}
