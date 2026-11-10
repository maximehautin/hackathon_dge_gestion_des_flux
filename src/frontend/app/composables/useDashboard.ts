import { sites, demoForecasts } from "~/data/sites";
import holidays from "~/data/holidays.json";
import vacations from "~/data/vacations.json";
import {
  forecastIndex,
  formatDate,
  mondayOffset,
  offsetDate,
  risk,
} from "~/utils/forecast";

export function useDashboard() {
  // useState serializes the Paris anchor for identical server/client rendering.
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
  const thresholds = ref({ moderate: 25, high: 40 });
  const site = computed(() => sites.find((s) => s.id === siteId.value)!);
  const monday = computed(() => mondayOffset(anchor.value));
  const lastWeek = computed(() => Math.floor((6 - monday.value) / 7));
  const cards = computed(() =>
    Array.from({ length: 7 }, (_, i) => {
      const date = offsetDate(anchor.value, monday.value + week.value * 7 + i);
      const index = forecastIndex(anchor.value, date);
      const forecast =
        site.value.available && index !== null ? demoForecasts[index]! : null;
      const vacation = vacations.find((v) => date >= v.start && date < v.end);
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
      onMounted(() => {
        refreshDate();
        timer = setInterval(refreshDate, 60_000);
        window.addEventListener("focus", refreshDate);
        document.addEventListener("visibilitychange", refreshDate);
      });
      onUnmounted(() => {
        clearInterval(timer);
        window.removeEventListener("focus", refreshDate);
        document.removeEventListener("visibilitychange", refreshDate);
      });
      return {
        date,
        forecast,
        level: forecast ? risk(forecast.peak, thresholds.value) : null,
        holiday: (holidays as Record<string, string>)[date],
        vacation: vacation?.name,
        today: date === anchor.value,
        past: date < anchor.value,
      };
    }),
  );
  const selected = computed(() =>
    cards.value.find((c) => c.date === selectedDate.value && c.forecast),
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
    selectedDate.value = cards.value.find((c) => c.forecast)?.date ?? "";
  }
  watch([week, siteId], selectFirstAvailable, { flush: "sync" });
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
    today,
  };
}
