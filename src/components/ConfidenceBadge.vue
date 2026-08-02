<script setup lang="ts">
import { computed } from 'vue'
import type { ConfidenceLevel } from '../types/trace'

const props = defineProps<{
  level?: ConfidenceLevel | null
}>()

const label = computed(() => (props.level ? props.level.toUpperCase() : 'UNKNOWN'))

const classes: Record<string, string> = {
  high: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  low: 'border-rose-200 bg-rose-50 text-rose-700',
  unknown: 'border-slate-200 bg-slate-50 text-slate-500',
}
</script>

<template>
  <span
    class="inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-bold tracking-wide"
    :class="classes[props.level || 'unknown']"
  >
    {{ label }}
  </span>
</template>
