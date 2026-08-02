<script setup lang="ts">
defineProps<{
  title: string
}>()
</script>

<template>
  <section class="border-b border-slate-200 p-4 last:border-b-0">
    <h3 class="text-xs font-bold uppercase tracking-wide text-slate-500">{{ title }}</h3>
    <div class="mt-3">
      <slot />
    </div>
  </section>
</template>
