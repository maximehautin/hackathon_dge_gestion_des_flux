<script setup lang="ts">
import type { SiteInfo, MetricsResponse } from '~/composables/useApi'

useHead({ title: "Performance du modèle — Isère" })

const config = useRuntimeConfig()
const base = import.meta.server
  ? ((config.apiBaseInternal as string) || (config.public.apiBase as string))
  : (config.public.apiBase as string)

const { data: sitesData } = await useFetch<SiteInfo[]>(`${base}/sites`)
const trainedSites = computed(() => (sitesData.value ?? []).filter(s => s.has_data))

const siteId = ref('herretang')

const { data: metrics, pending, error } = useFetch<MetricsResponse>(
  () => `${base}/metrics/${siteId.value}`,
  { watch: [siteId] },
)

const featureLabels: Record<string, string> = {
  mois: 'Mois',
  jour_semaine: 'Jour de la semaine',
  weekend: 'Week-end',
  jour_ferie: 'Jour férié',
  vacances_scolaires_zone_a: 'Vacances scolaires (zone A)',
  temperature_moy: 'Température moyenne',
  precipitations_mm: 'Précipitations (mm)',
  pluie_heures: 'Heures de pluie',
  neige_oui_non_jour: 'Neige',
  passages_j1: 'Passages J−1',
  passages_j7: 'Passages J−7',
  passages_j365: 'Passages J−365',
}

const sortedFeatures = computed(() => {
  const fi = metrics.value?.feature_importance
  if (!fi) return []
  const max = Math.max(...Object.values(fi))
  return Object.entries(fi)
    .map(([key, val]) => ({
      key,
      label: featureLabels[key] ?? key,
      val,
      pct: Math.round((val / max) * 100),
    }))
    .sort((a, b) => b.val - a.val)
})

const heroSiteName = computed(
  () =>
    metrics.value?.site.nom ??
    trainedSites.value.find(s => s.id === siteId.value)?.nom ??
    'Site',
)

const bestRun = computed(() => metrics.value?.runs.find(r => r.is_best))

function fmt1(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : '—'
}

function fmtPct(v: number | null | undefined): string {
  return v != null ? `${Math.round(v * 100)} %` : '—'
}
</script>

<template>
  <SiteHeader
    :site-name="heroSiteName"
    hero-title="Performance du modèle IA"
    hero-subtitle="Métriques d'évaluation et importances des variables par site"
  />
  <main class="model-main">
    <div class="model-controls">
      <label for="modelSiteSelect">Site touristique</label>
      <select id="modelSiteSelect" v-model="siteId">
        <option v-for="site in trainedSites" :key="site.id" :value="site.id">
          {{ site.nom }}
        </option>
      </select>
    </div>

    <div v-if="pending" class="loading" aria-live="polite">Chargement des métriques…</div>
    <div v-else-if="error" class="api-error" role="alert">
      Aucun entraînement disponible pour ce site. Lancez d'abord l'entraînement depuis le tableau de bord.
    </div>
    <template v-else-if="metrics">

      <section class="method-note">
        <strong>Protocole d'évaluation</strong> —
        Entraînement 2022–2024 (années COVID 2020–2021 exclues) ·
        Évaluation hors-échantillon sur 2025 ·
        {{ metrics.runs[0]?.params.train_jours ?? '—' }} jours d'apprentissage ·
        {{ metrics.runs[0]?.params.holdout_jours ?? '—' }} jours de test ·
        3 runs XGBoost avec hyperparamètres distincts, meilleur run sélectionné par MAE
      </section>

      <section class="runs-section">
        <h2>Comparaison des runs</h2>
        <div class="table-wrap">
          <table class="runs-table">
            <thead>
              <tr>
                <th>Modèle</th>
                <th title="Nombre d'arbres">Arbres</th>
                <th title="Profondeur max des arbres">Prof.</th>
                <th title="Taux d'apprentissage">LR</th>
                <th title="MAE sur le jeu de test 2025 — passages/jour">MAE (j)</th>
                <th title="RMSE sur le jeu de test 2025 — passages/jour">RMSE (j)</th>
                <th title="MAE / médiane observée × 100">MAE/méd.</th>
                <th title="Part des jours à forte fréquentation correctement classés">Alertes élevées</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="run in metrics.runs"
                :key="run.run_id"
                :class="{ best: run.is_best }"
              >
                <td>
                  <span v-if="run.is_best" class="best-badge">✓ Meilleur</span>
                  <span v-else class="run-name">{{ run.run_name }}</span>
                </td>
                <td>{{ run.params.n_estimators ?? '—' }}</td>
                <td>{{ run.params.max_depth ?? '—' }}</td>
                <td>{{ run.params.learning_rate ?? '—' }}</td>
                <td class="num">{{ fmt1(run.metrics.mae_holdout) }}</td>
                <td class="num">{{ fmt1(run.metrics.rmse_holdout) }}</td>
                <td class="num">{{ fmt1(run.metrics.mae_normalisee_holdout) }} %</td>
                <td class="num">{{ fmtPct(run.metrics.precision_alerte_elevee) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="table-note">
          <strong>MAE</strong> erreur absolue moyenne ·
          <strong>RMSE</strong> racine de l'erreur quadratique moyenne ·
          <strong>MAE/méd.</strong> erreur relative (% de la médiane des passages observés) ·
          <strong>Alertes élevées</strong> proportion de jours à forte affluence correctement classés
        </p>
      </section>

      <section v-if="sortedFeatures.length" class="fi-section">
        <h2>Importances des variables</h2>
        <p class="fi-intro">
          Contribution relative de chaque signal à la décision du meilleur modèle
          <em>({{ bestRun?.run_name }})</em>.
          Calculé sur le jeu d'entraînement via le gain moyen des arbres XGBoost.
        </p>
        <div class="fi-list">
          <div v-for="f in sortedFeatures" :key="f.key" class="fi-row">
            <div class="fi-label">{{ f.label }}</div>
            <div class="fi-bar-wrap">
              <div class="fi-bar" :style="{ width: f.pct + '%' }" />
            </div>
            <div class="fi-val">{{ (f.val * 100).toFixed(1) }} %</div>
          </div>
        </div>
      </section>

    </template>
  </main>
</template>

<style scoped>
.model-main {
  max-width: 1120px;
  margin: auto;
  padding: 36px 30px 60px;
}

.model-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
  font-size: 16px;
}
.model-controls label {
  color: var(--text-muted);
}
.model-controls select {
  padding: 6px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  background: var(--bg-page);
  font-size: 16px;
}

.method-note {
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  font-size: 15px;
  color: var(--text-muted);
  margin-bottom: 36px;
  line-height: 1.6;
}

.runs-section,
.fi-section {
  margin-bottom: 48px;
}

h2 {
  font-size: 19px;
  font-weight: 700;
  color: var(--text-title);
  margin: 0 0 16px;
}

.table-wrap {
  overflow-x: auto;
}
.runs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 15px;
}
.runs-table th {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 2px solid var(--border-default);
  color: var(--text-muted);
  font-weight: 600;
  white-space: nowrap;
}
.runs-table td {
  padding: 11px 12px;
  border-bottom: 1px solid var(--border-default);
  vertical-align: middle;
}
.runs-table tr.best td {
  background: #f0f0ff;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.best-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  background: var(--blue-france);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.run-name {
  color: var(--text-muted);
}
.table-note {
  font-size: 13px;
  color: var(--text-muted);
  margin: 10px 0 0;
  line-height: 1.8;
}

.fi-intro {
  font-size: 15px;
  color: var(--text-muted);
  margin: 0 0 20px;
  line-height: 1.6;
}
.fi-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.fi-row {
  display: grid;
  grid-template-columns: 220px 1fr 56px;
  align-items: center;
  gap: 14px;
}
.fi-label {
  font-size: 15px;
  color: var(--text-body);
}
.fi-bar-wrap {
  height: 10px;
  background: var(--bg-subtle);
  border-radius: var(--radius-pill);
  overflow: hidden;
}
.fi-bar {
  height: 100%;
  background: var(--blue-france);
  border-radius: var(--radius-pill);
  transition: width 0.4s ease;
}
.fi-val {
  font-size: 14px;
  color: var(--text-muted);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.loading {
  padding: 48px;
  text-align: center;
  color: var(--text-muted);
}
</style>
