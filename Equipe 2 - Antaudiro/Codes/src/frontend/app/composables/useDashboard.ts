import holidays from "~/data/holidays.json";
import vacations from "~/data/vacations.json";
import {
  forecastIndex,
  formatDate,
  mondayOffset,
  offsetDate,
  risk,
} from "~/utils/forecast";
import type { SiteInfo, PredictResponse, TrainStatus } from "~/composables/useApi";

export function useDashboard() {
  const { fetchSites, fetchPredict, fetchHistory, triggerTrain, fetchTrainStatus } = useApi();

  const anchor = useState("forecast-anchor", () =>
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Paris",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
  );
  const siteId = ref("herretang");
  const week = ref(0);
  const selectedDate = ref(anchor.value);
  const thresholds = ref({ moderate: 180, high: 255 });

  const loading = ref(false);
  const error = ref<string | null>(null);
  const apiSites = ref<SiteInfo[]>([]);
  const predictData = ref<PredictResponse | null>(null);
  const historyData = ref<Record<string, number>>({});
  const trainStatus = ref<TrainStatus>("idle");
  const sites = computed(() =>
    apiSites.value.map((s) => ({
      id: s.id,
      name: s.nom,
      available: s.ready,
      has_data: s.has_data,
    })),
  );
  const site = computed(
    () =>
      sites.value.find((s) => s.id === siteId.value) ?? {
        id: siteId.value,
        name: siteId.value,
        available: false,
        has_data: false,
      },
  );
  const monday = computed(() => mondayOffset(anchor.value));
  const lastWeek = computed(() => Math.floor((6 - monday.value) / 7));

  async function loadSites() {
    try {
      apiSites.value = await fetchSites();
    } catch {
      // Silencieux : la liste reste vide tant que l'API est indisponible
    }
  }

  let thresholdsInitialized = false;
  async function loadPredict(id: string) {
    loading.value = true;
    error.value = null;
    predictData.value = null;
    try {
      predictData.value = await fetchPredict(id);
      if (!thresholdsInitialized) {
        thresholds.value = {
          moderate: predictData.value.seuils_abs.modere,
          high: predictData.value.seuils_abs.eleve,
        };
        thresholdsInitialized = true;
      }
    } catch (e: unknown) {
      const status =
        e && typeof e === "object" && "status" in e ? (e as { status: number }).status : 0;
      if (status !== 503) {
        error.value = "API indisponible — données non chargées.";
      }
    } finally {
      loading.value = false;
    }
  }

  async function loadHistory(id: string, from: string, to: string) {
    if (!site.value.has_data) {
      historyData.value = {};
      return;
    }
    try {
      const entries = await fetchHistory(id, from, to);
      const map: Record<string, number> = {};
      for (const e of entries) map[e.date] = e.passages_jour;
      historyData.value = map;
    } catch {
      historyData.value = {};
    }
  }

  // Polling d'état de l'entraînement
  let trainPollTimer: ReturnType<typeof setInterval> | undefined;

  async function trainSite() {
    trainStatus.value = "training";
    try {
      await triggerTrain(siteId.value);
    } catch {
      trainStatus.value = "error";
      return;
    }
    trainPollTimer = setInterval(async () => {
      try {
        const { status, ready } = await fetchTrainStatus(siteId.value);
        if (status === "done" || ready) {
          clearInterval(trainPollTimer);
          trainStatus.value = "done";
          await loadSites();
          await loadPredict(siteId.value);
        } else if (status === "error") {
          clearInterval(trainPollTimer);
          trainStatus.value = "error";
        }
      } catch {}
    }, 3000);
  }

  function refreshDate() {
    const date = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Paris",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
    if (date !== anchor.value) {
      anchor.value = date;
      today();
    }
  }
  let timer: ReturnType<typeof setInterval> | undefined;
  onMounted(async () => {
    refreshDate();
    timer = setInterval(refreshDate, 60_000);
    window.addEventListener("focus", refreshDate);
    document.addEventListener("visibilitychange", refreshDate);
    await loadSites();
    await loadPredict(siteId.value);
  });
  onUnmounted(() => {
    clearInterval(timer);
    clearInterval(trainPollTimer);
    window.removeEventListener("focus", refreshDate);
    document.removeEventListener("visibilitychange", refreshDate);
  });

  const cards = computed(() =>
    Array.from({ length: 7 }, (_, i) => {
      const date = offsetDate(anchor.value, monday.value + week.value * 7 + i);
      const index = forecastIndex(anchor.value, date);
      const dayData =
        site.value.available && index !== null
          ? (predictData.value?.predictions[index] ?? null)
          : null;
      const forecast = dayData
        ? {
            total: dayData.passages_prevus,
            peak: dayData.pic_horaire_estime,
            rain: dayData.precipitations_mm,
            snow: dayData.neige ?? false,
            reference: dayData.passages_reference,
          }
        : null;
      const historical =
        !forecast && date < anchor.value && site.value.has_data
          ? (historyData.value[date] ?? null)
          : null;
      const vacation = vacations.find((v) => date >= v.start && date < v.end);
      return {
        date,
        forecast,
        historical,
        level: forecast
          ? risk(forecast.total, thresholds.value)
          : historical !== null
            ? risk(historical, thresholds.value)
            : null,
        holiday: (holidays as Record<string, string>)[date],
        vacation: vacation?.name,
        today: date === anchor.value,
        past: date < anchor.value,
      };
    }),
  );

  // Charger l'historique quand on navigue vers une semaine passée
  watch(
    [week, siteId],
    ([w, id]) => {
      if (w < 0) {
        const from = cards.value[0]!.date;
        const to = cards.value[6]!.date;
        loadHistory(id, from, to);
      } else {
        historyData.value = {};
      }
    },
    { flush: "post" },
  );

  const selected = computed(() =>
    cards.value.find(
      (c) => c.date === selectedDate.value && (c.forecast !== null || c.historical !== null),
    ),
  );
  const periodLabel = computed(() => {
    const first = cards.value[0]!.date;
    const last = cards.value[6]!.date;
    return (
      formatDate(first, {
        day: "numeric",
        month: "short",
        ...(first.slice(0, 4) !== last.slice(0, 4) ? { year: "numeric" } : {}),
      }) +
      " — " +
      formatDate(last, { day: "numeric", month: "short", year: "numeric" })
    );
  });
  function selectFirstAvailable() {
    selectedDate.value =
      cards.value.find((c) => c.forecast !== null || c.historical !== null)?.date ?? "";
  }
  watch([week, siteId], selectFirstAvailable, { flush: "sync" });
  watch(siteId, async (id) => {
    trainStatus.value = "idle";
    await loadPredict(id);
    selectFirstAvailable();
  });
  function today() {
    week.value = 0;
    selectedDate.value = anchor.value;
  }
  return {
    anchor,
    siteId,
    site,
    sites,
    week,
    lastWeek,
    cards,
    selectedDate,
    selected,
    thresholds,
    periodLabel,
    loading,
    error,
    today,
    trainStatus,
    trainSite,
  };
}
