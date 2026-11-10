<script setup lang="ts">
import { validThresholds, type Thresholds } from "~/utils/forecast";
const model = defineModel<Thresholds>({ required: true });
const moderate = ref(model.value.moderate);
const high = ref(model.value.high);
const valid = computed(() =>
  validThresholds(Number(moderate.value), Number(high.value)),
);
const scale = ref(100);
watch([moderate, high], () => {
  if (!valid.value) return;
  scale.value = Math.max(
    scale.value,
    Math.ceil(Number(high.value) / 100) * 100,
  );
  model.value = { moderate: Number(moderate.value), high: Number(high.value) };
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
      <div
        v-for="key in ['moderate', 'high'] as const"
        :key="key"
        class="threshold-editor"
      >
        <label :for="key"
          ><i class="dot" :class="{ 'red-dot': key === 'high' }" />Vigilance
          {{ key === "moderate" ? "modérée" : "élevée" }}</label
        >
        <div class="threshold-input">
          <span>À partir de</span
          ><input
            :id="key"
            :value="key === 'moderate' ? moderate : high"
            type="number"
            :min="key === 'moderate' ? 1 : moderate + 1"
            :max="key === 'moderate' ? high - 1 : 2000"
            :aria-invalid="!valid"
            @input="
              key === 'moderate'
                ? (moderate = Number(($event.target as HTMLInputElement).value))
                : (high = Number(($event.target as HTMLInputElement).value))
            "
          /><span>passages / j</span>
        </div>
        <input
          :aria-label="key === 'moderate' ? 'Seuil modéré' : 'Seuil élevé'"
          type="range"
          :min="key === 'moderate' ? 1 : moderate + 1"
          :max="key === 'moderate' ? high - 1 : scale"
          :value="key === 'moderate' ? moderate : high"
          @input="
            key === 'moderate'
              ? (moderate = Number(($event.target as HTMLInputElement).value))
              : (high = Number(($event.target as HTMLInputElement).value))
          "
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
