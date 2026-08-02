<script setup lang="ts">
defineProps<{
  label?: string
  compact?: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-2 text-sm text-slate-500" :class="{ 'py-3': !compact }">
    <span
      class="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600"
      aria-hidden="true"
    />
    <span>{{ label || 'Loading' }}</span>
  </div>
</template>
