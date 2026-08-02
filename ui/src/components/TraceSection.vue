<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'

defineProps<{
  title: string
  expanded: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()
</script>

<template>
  <section class="border-b border-slate-200 last:border-b-0">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50"
      :aria-expanded="expanded"
      @click="emit('toggle')"
    >
      <h3 class="text-xs font-bold uppercase tracking-wide text-slate-500">{{ title }}</h3>
      <ChevronDown class="h-4 w-4 text-slate-400 transition" :class="{ 'rotate-180': expanded }" />
    </button>
    <div v-show="expanded" class="px-4 pb-4">
      <slot />
    </div>
  </section>
</template>
