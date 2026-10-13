<script setup lang="ts">
import { ref } from "vue"

import DailyLeavePage from "./DailyLeavePage.vue"
import CampLeavePage from "./CampLeavePage.vue"
import LegacySchoolLeaveHistory from "./LegacySchoolLeaveHistory.vue"
import type { Member } from "../types"

const props = defineProps<{ currentUser: Member }>()
const emit = defineEmits<{ navigate: [path: string]; todoCount: [count: number]; unreadCount: [count: number] }>()
const activeSection = ref<"daily" | "camp" | "records">("daily")
const isAdmin = props.currentUser.role === "admin"
</script>

<template>
  <nav class="leave-kind-tabs" aria-label="请假类型">
    <button type="button" :class="{ active: activeSection === 'daily' }" @click="activeSection = 'daily'">日常请假</button>
    <button type="button" :class="{ active: activeSection === 'camp' }" @click="activeSection = 'camp'">集中请假</button>
    <button v-if="isAdmin" type="button" :class="{ active: activeSection === 'records' }" @click="activeSection = 'records'">请假记录</button>
  </nav>

  <template v-if="activeSection === 'daily'">
    <div class="page-title leave-page-title"><h1>日常请假</h1></div>
    <DailyLeavePage
      :current-user="props.currentUser"
      @navigate="emit('navigate', $event)"
      @todo-count="emit('todoCount', $event)"
    />
  </template>
  <template v-else-if="activeSection === 'camp'">
    <div class="page-title leave-page-title"><h1>集中请假</h1></div>
    <CampLeavePage :current-user="props.currentUser" @navigate="emit('navigate', $event)" />
  </template>
  <template v-else-if="isAdmin">
    <div class="page-title leave-page-title"><h1>请假记录</h1></div>
    <LegacySchoolLeaveHistory :current-user="props.currentUser" @unread-count="emit('unreadCount', $event)" />
  </template>
</template>

<style scoped>
.leave-kind-tabs { display: flex; gap: 18px; margin: 0 0 22px; border-bottom: 1px solid var(--line); }
.leave-kind-tabs button { padding: 0 0 8px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font: inherit; font-size: 13px; cursor: pointer; }
.leave-kind-tabs button.active { border-bottom-color: var(--primary); color: var(--text); }
.leave-page-title { margin-bottom: 18px; }
</style>
