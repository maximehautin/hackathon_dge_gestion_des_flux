<script setup lang="ts">
import { validThresholds, type Thresholds } from "~/utils/forecast";
const model = defineModel<Thresholds>({ required: true });
const moderate = ref(model.value.moderate);
const high = ref(model.value.high);
const valid = computed(() =>
  validThresholds(Number(moderate.value), Number(high.value)),
);
const scale = ref(Math.ceil(model.value.high / 100) * 100);
watch(() => model.value, (newVal) => {
  moderate.value = newVal.moderate;
  high.value = newVal.high;
  scale.value = Math.max(scale.value, Math.ceil(newVal.high / 100) * 100);
});
watch([moderate, high], () => {
  if (!valid.value) return;
  scale.value = Math.max(
    scale.value,
    Math.ceil(Number(high.value) / 100) * 100,
  );
  const m = Number(moderate.value), h = Number(high.value);
  if (m !== model.value.moderate || h !== model.value.high)
    model.value = { moderate: m, high: h };
});
</script>
<template>
  <section class="panel threshold-panel" aria-labelledby="thresholdTitle">
    <div class="threshold-heading">
      <div>
        <h2 id="thresholdTitle">Vos seuils de vigilance</h2>
        <p class="threshold-description">
          Choisissez à partir de combien de passages par jour le niveau change.
        </p>
      </div>
      <span class="unit-tag">Passages / jour</span>
    </div>
    <div class="threshold-editors">
      <div class="threshold-editor">
        <label for="moderate"><i class="dot" />Vigilance modérée</label>
        <div class="threshold-input">
          <span>À partir de</span>
          <input
            id="moderate"
            v-model.number="moderate"
            type="number"
            :min="1"
            :max="high - 1"
            :aria-invalid="!valid"
          />
          <span>passages / j</span>
        </div>
        <input
          aria-label="Seuil modéré"
          type="range"
          :min="1"
          :max="high - 1"
          :value="moderate"
          @input="moderate = Number(($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="threshold-editor">
        <label for="high"><i class="dot red-dot" />Vigilance élevée</label>
        <div class="threshold-input">
          <span>À partir de</span>
          <input
            id="high"
            v-model.number="high"
            type="number"
            :min="moderate + 1"
            :max="2000"
            :aria-invalid="!valid"
          />
          <span>passages / j</span>
        </div>
        <input
          aria-label="Seuil élevé"
          type="range"
          :min="moderate + 1"
          :max="scale"
          :value="high"
          @input="high = Number(($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>
    <div class="threshold-preview" aria-live="polite">
      <div>
        <i class="preview-line low-line" /> <strong>Faible</strong
        ><span>Moins de {{ model.moderate }}</span>
      </div>
      <div>
        <i class="preview-line moderate-line" /> <strong>Modérée</strong
        ><span>{{ model.moderate }} à {{ model.high - 1 }}</span>
      </div>
      <div>
        <i class="preview-line high-line" /> <strong>Élevée</strong
        ><span>{{ model.high }} et plus</span>
      </div>
    </div>
    <p v-if="!valid" role="alert" class="note" style="color:#a22">
      Le seuil élevé doit être supérieur au seuil modéré (entiers de 1 à 2 000). Les dernières
      valeurs valides restent appliquées.
    </p>
    <div class="threshold-bottom">
      <p class="note">
        Ces seuils portent sur les passages journaliers, pas sur l’occupation du
        site.
      </p>
      <span class="auto-apply" role="status"
        ><i v-if="valid" />{{
          valid ? "Application automatique" : "Valeurs à corriger"
        }}</span
      >
    </div>
  </section>
</template>
