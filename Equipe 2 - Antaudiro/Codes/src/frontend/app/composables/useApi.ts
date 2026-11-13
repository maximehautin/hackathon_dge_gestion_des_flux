export interface SiteInfo {
  id: string;
  nom: string;
  commune?: string;
  has_data: boolean;
  ready: boolean;
}

export interface DayForecast {
  date: string;
  passages_prevus: number;
  pic_horaire_estime: number;
  passages_reference: number;
  precipitations_mm: number;
  neige: boolean;
  risque: string;
  jour_ferie: boolean;
  vacances: boolean;
}

export interface PredictResponse {
  capacite: number;
  seuils_abs: { modere: number; eleve: number };
  predictions: DayForecast[];
}

export interface HistoryEntry {
  date: string;
  passages_jour: number;
}

export type TrainStatus = "idle" | "training" | "done" | "error";

export interface TrainStatusResponse {
  status: TrainStatus;
  ready: boolean;
}

export interface MetricsRun {
  run_id: string;
  run_name: string;
  is_best: boolean;
  metrics: {
    mae_holdout: number | null;
    rmse_holdout: number | null;
    mae_normalisee_holdout: number | null;
    precision_alerte_elevee: number | null;
  };
  params: {
    n_estimators: string | null;
    max_depth: string | null;
    learning_rate: string | null;
    subsample: string | null;
    train_jours: string | null;
    holdout_jours: string | null;
  };
}

export interface MetricsResponse {
  site: { id: string; nom: string; commune: string };
  runs: MetricsRun[];
  feature_importance: Record<string, number> | null;
}

export function useApi() {
  const config = useRuntimeConfig();
  const base = import.meta.server
    ? ((config.apiBaseInternal as string) || (config.public.apiBase as string))
    : (config.public.apiBase as string);

  async function fetchSites(): Promise<SiteInfo[]> {
    return $fetch<SiteInfo[]>(`${base}/sites`);
  }

  async function fetchPredict(siteId: string): Promise<PredictResponse> {
    return $fetch<PredictResponse>(`${base}/predict/${siteId}`);
  }

  async function fetchHistory(siteId: string, from: string, to: string): Promise<HistoryEntry[]> {
    return $fetch<HistoryEntry[]>(`${base}/history/${siteId}`, {
      params: { from, to },
    });
  }

  async function triggerTrain(siteId: string): Promise<{ status: string }> {
    return $fetch<{ status: string }>(`${base}/train/${siteId}`, { method: "POST" });
  }

  async function fetchTrainStatus(siteId: string): Promise<TrainStatusResponse> {
    return $fetch<TrainStatusResponse>(`${base}/train/${siteId}/status`);
  }

  async function fetchMetrics(siteId: string): Promise<MetricsResponse> {
    return $fetch<MetricsResponse>(`${base}/metrics/${siteId}`);
  }

  return { fetchSites, fetchPredict, fetchHistory, triggerTrain, fetchTrainStatus, fetchMetrics };
}
