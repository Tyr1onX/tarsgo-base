<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { api } from "../api"
import ActionMenu, { type ActionMenuItem } from "../components/ActionMenu.vue"
import ConfirmDialog from "../components/ConfirmDialog.vue"
import type { DailyLeaveWindowAdmin, DailyLeaveWindowMember, Member } from "../types"

const props = defineProps<{ currentUser: Member }>()
const emit = defineEmits<{ navigate: [path: string]; todoCount: [count: number] }>()

interface CloseRequest {
  title: string
  description: string
  confirmLabel: string
  action: () => Promise<void>
}

const memberWindows = ref<DailyLeaveWindowMember[]>([])
const adminWindows = ref<DailyLeaveWindowAdmin[]>([])
const loading = ref(true)
const savingWindow = ref(false)
const downloadingSelf = ref(false)
const downloadingId = ref<number | null>(null)
const error = ref("")
const notice = ref("")
const readyDownload = ref<{ download_url: string; filename: string } | null>(null)
const showCreateForm = ref(false)
const closeRequest = ref<CloseRequest | null>(null)
const closePending = ref(false)
const selfDraft = ref({ start_at: "", end_at: "" })
const windowDraft = ref({ title: "", start_at: "", end_at: "" })

const isAdmin = computed(() => props.currentUser.role === "admin")
const profileReady = computed(() =>
  props.currentUser.name.trim().length >= 2 && props.currentUser.name.trim().length <= 50 &&
  /^[0-9]{8}$/.test(props.currentUser.student_id ?? "") &&
  Boolean(props.currentUser.college),
)
const sharedWindows = computed(() => {
  if (isAdmin.value) {
    return adminWindows.value.filter((item) => item.status === "open" && item.accepting_participants)
  }
  return memberWindows.value
})

function messageOf(reason: unknown) {
  if (reason instanceof TypeError) {
    return "网络请求未能完成。请检查网络后重试；同一请假时段会复用已有事项，不会重复创建。"
  }
  return reason instanceof Error ? reason.message : "操作失败"
}

function dateTime(value: string) {
  return value.slice(0, 16).replace("T", " ")
}

function initializeDailyTimesIfEmpty(draft: { start_at: string; end_at: string }) {
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`
  if (!draft.start_at) draft.start_at = `${today}T08:00`
  if (!draft.end_at) draft.end_at = `${today}T17:10`
}

function toggleCreateForm() {
  showCreateForm.value = !showCreateForm.value
  if (showCreateForm.value) initializeDailyTimesIfEmpty(windowDraft.value)
}

function range(item: Pick<DailyLeaveWindowMember, "start_at" | "end_at">) {
  return `${dateTime(item.start_at)} 至 ${dateTime(item.end_at)}`
}

function requestNativeDownload(downloadUrl: string) {
  const anchor = document.createElement("a")
  anchor.href = downloadUrl
  anchor.rel = "noopener"
  anchor.referrerPolicy = "no-referrer"
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

async function load() {
  loading.value = true
  error.value = ""
  try {
    const [mine, admin] = await Promise.all([
      api.dailyLeaveWindows(),
      isAdmin.value ? api.dailyLeaveAdminWindows() : Promise.resolve([]),
    ])
    memberWindows.value = mine
    adminWindows.value = admin
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    loading.value = false
  }
  emit("todoCount", 0)
}

function validateRange(start: string, end: string) {
  if (!start || !end) return "请填写开始时间和结束时间。"
  if (new Date(start).getTime() >= new Date(end).getTime()) return "结束时间必须晚于开始时间。"
  return ""
}

async function generateSelf(offline = false) {
  if (downloadingSelf.value) return
  error.value = ""
  notice.value = ""
  readyDownload.value = null
  if (!profileReady.value) {
    error.value = "请先完善姓名、8 位学号和学院后再生成。"
    return
  }
  const rangeError = validateRange(selfDraft.value.start_at, selfDraft.value.end_at)
  if (rangeError) {
    error.value = rangeError
    return
  }
  downloadingSelf.value = true
  try {
    const file = await api.generateDailyLeaveSelfServiceDocument({
      start_at: selfDraft.value.start_at,
      end_at: selfDraft.value.end_at,
    }, offline)
    readyDownload.value = file
    requestNativeDownload(file.download_url)
    notice.value = "请假事项已保存，正在向浏览器发起文件请求。请检查下载列表或文件管理器确认保存；若未出现文件，使用下方链接重试，不会新增事项。"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    downloadingSelf.value = false
  }
}

async function generateShared(item: DailyLeaveWindowMember, offline = false) {
  if (downloadingId.value !== null) return
  error.value = ""
  notice.value = ""
  readyDownload.value = null
  if (!profileReady.value) {
    error.value = "请先完善姓名、8 位学号和学院后再生成。"
    return
  }
  downloadingId.value = item.id
  try {
    const file = await api.prepareDailyLeaveWindowDocument(item.id, offline)
    readyDownload.value = file
    requestNativeDownload(file.download_url)
    notice.value = "共享报名已保存，正在向浏览器发起文件请求。请检查下载列表或文件管理器确认保存；若未出现文件，使用下方链接重试。"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    downloadingId.value = null
  }
}

function memberMenuActions(item: DailyLeaveWindowMember): ActionMenuItem[] {
  return [{ key: "offline", label: "下载线下签章版", disabled: downloadingId.value === item.id }]
}

function adminMenuActions(item: DailyLeaveWindowAdmin): ActionMenuItem[] {
  const actions: ActionMenuItem[] = []
  if (!item.public_enabled && item.accepting_participants) {
    actions.push({ key: "enable-public", label: "开启临时公开链接" })
  }
  if (item.status === "open") actions.push({ key: "close", label: "关闭共享活动", danger: true })
  return actions
}

function absolutePublicLink(item: DailyLeaveWindowAdmin) {
  return item.public_path ? new URL(item.public_path, window.location.origin).toString() : ""
}

async function copyPublicLink(item: DailyLeaveWindowAdmin) {
  const link = absolutePublicLink(item)
  if (!link) return
  try {
    await navigator.clipboard.writeText(link)
    notice.value = "公开链接已复制。"
  } catch {
    notice.value = `公开链接：${link}`
  }
}

async function createSharedActivity() {
  error.value = ""
  notice.value = ""
  const rangeError = validateRange(windowDraft.value.start_at, windowDraft.value.end_at)
  if (rangeError) {
    error.value = rangeError
    return
  }
  if (!windowDraft.value.title.trim()) {
    error.value = "请填写仅供管理识别的活动名称。"
    return
  }
  savingWindow.value = true
  try {
    await api.createDailyLeaveWindow({
      title: windowDraft.value.title.trim(),
      start_at: windowDraft.value.start_at,
      end_at: windowDraft.value.end_at,
    })
    windowDraft.value = { title: "", start_at: "", end_at: "" }
    showCreateForm.value = false
    notice.value = "共享活动已创建。公开链接可稍后按需开启。"
    await load()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    savingWindow.value = false
  }
}

function handleAdminMenu(item: DailyLeaveWindowAdmin, action: string) {
  if (action === "enable-public") {
    void (async () => {
      error.value = ""
      try {
        await api.enableDailyLeavePublicLink(item.id)
        notice.value = "临时公开链接已开启。"
        await load()
      } catch (reason) {
        error.value = messageOf(reason)
      }
    })()
    return
  }
  if (action === "close") {
    closeRequest.value = {
      title: "关闭共享活动？",
      description: "关闭后，成员和公开链接都不能继续生成请假条。",
      confirmLabel: "关闭活动",
      action: async () => {
        await api.closeDailyLeaveWindow(item.id)
        notice.value = "共享活动已关闭。"
        await load()
      },
    }
  }
}

async function confirmClose() {
  const pending = closeRequest.value
  if (!pending) return
  closePending.value = true
  error.value = ""
  try {
    await pending.action()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    closePending.value = false
    closeRequest.value = null
  }
}

function handleMemberMenu(item: DailyLeaveWindowMember, action: string) {
  if (action === "offline") void generateShared(item, true)
}

function handleAdminMenuSelect(item: DailyLeaveWindowAdmin, action: string) {
  if (action === "offline") void generateShared(item, true)
  else handleAdminMenu(item, action)
}

onMounted(() => {
  initializeDailyTimesIfEmpty(selfDraft.value)
  void load()
})
</script>

<template>
  <ConfirmDialog
    :open="closeRequest !== null"
    :title="closeRequest?.title ?? ''"
    :description="closeRequest?.description ?? ''"
    :confirm-label="closeRequest?.confirmLabel ?? '确认'"
    danger
    :pending="closePending"
    @cancel="closePending ? undefined : (closeRequest = null)"
    @confirm="confirmClose"
  />

  <div class="daily-leave-page">
    <p v-if="error" class="daily-leave-feedback daily-leave-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="daily-leave-feedback daily-leave-notice" role="status">{{ notice }}</p>
    <p v-if="readyDownload" class="daily-leave-feedback daily-leave-notice">
      <a :href="readyDownload.download_url" referrerpolicy="no-referrer">若未看到文件，请点此重新下载。</a>
    </p>

    <section class="daily-leave-section daily-leave-self">
      <div class="daily-leave-heading"><h2>生成请假条</h2></div>
      <p v-if="!profileReady" class="daily-leave-muted">
        请先完善姓名、8 位学号和学院。
        <button class="text-action" type="button" @click="emit('navigate', '/me/edit')">去完善资料</button>
      </p>
      <form class="daily-leave-self-form" @submit.prevent="generateSelf(false)">
        <label>
          <span>开始时间</span>
          <input v-model="selfDraft.start_at" type="datetime-local" required />
        </label>
        <label>
          <span>结束时间</span>
          <input v-model="selfDraft.end_at" type="datetime-local" required />
        </label>
        <div class="daily-leave-self-actions">
          <button class="primary" type="submit" :disabled="downloadingSelf || !profileReady">
            {{ downloadingSelf ? "正在准备文件…" : "生成并下载请假条" }}
          </button>
          <ActionMenu
            id="daily-self-service-document"
            aria-label="其他下载选项"
            :disabled="downloadingSelf || !profileReady"
            :actions="[{ key: 'offline', label: '下载线下签章版' }]"
            @select="(action) => action === 'offline' && generateSelf(true)"
          />
        </div>
      </form>
    </section>
    <section v-if="sharedWindows.length || loading || isAdmin" class="daily-leave-section daily-leave-shared">
      <div class="daily-leave-heading">
        <h2>共享活动</h2>
        <button v-if="isAdmin" class="text-action" type="button" @click="toggleCreateForm">
          {{ showCreateForm ? "取消创建" : "＋ 创建共享活动" }}
        </button>
      </div>
      <p v-if="loading" class="daily-leave-muted" role="status">正在读取共享活动…</p>
      <div v-else-if="sharedWindows.length" class="daily-leave-list">
        <article v-for="item in sharedWindows" :key="item.id" class="daily-leave-row">
          <div class="daily-leave-main">
            <strong>{{ item.title }}</strong>
            <span>{{ range(item) }}</span>
            <small v-if="isAdmin && 'entry_count' in item">{{ item.entry_count }} 人已生成</small>
            <div v-if="isAdmin && 'public_path' in item && item.public_path" class="daily-leave-link">
              <a :href="item.public_path" target="_blank" rel="noreferrer">{{ absolutePublicLink(item) }}</a>
              <button class="text-action" type="button" @click="copyPublicLink(item)">复制链接</button>
            </div>
          </div>
          <div class="daily-leave-actions">
            <button class="text-action" type="button" :disabled="!profileReady || downloadingId !== null" @click="generateShared(item)">
              {{ downloadingId === item.id ? "正在准备文件…" : "一键生成" }}
            </button>
            <ActionMenu
              v-if="isAdmin"
              :id="`daily-shared-admin-${item.id}`"
              aria-label="共享活动操作"
              :disabled="downloadingId !== null"
              :actions="[...adminMenuActions(item), { key: 'offline', label: '下载线下签章版' }]"
              @select="handleAdminMenuSelect(item, $event)"
            />
            <ActionMenu
              v-else
              :id="`daily-shared-${item.id}`"
              aria-label="其他下载选项"
              :disabled="downloadingId !== null || !profileReady"
              :actions="memberMenuActions(item)"
              @select="handleMemberMenu(item, $event)"
            />
          </div>
        </article>
      </div>
      <p v-else-if="!isAdmin" class="daily-leave-muted">当前没有可用共享活动。</p>

      <form v-if="isAdmin && showCreateForm" class="daily-leave-create-form" @submit.prevent="createSharedActivity">
        <label class="daily-leave-title-field">
          <span>内部活动名称</span>
          <input v-model="windowDraft.title" maxlength="100" required autocomplete="off" placeholder="仅供系统留档和管理识别" />
        </label>
        <label>
          <span>开始时间</span>
          <input v-model="windowDraft.start_at" type="datetime-local" required />
        </label>
        <label>
          <span>结束时间</span>
          <input v-model="windowDraft.end_at" type="datetime-local" required />
        </label>
        <button class="primary daily-leave-submit" type="submit" :disabled="savingWindow">
          {{ savingWindow ? "正在创建…" : "创建共享活动" }}
        </button>
      </form>
      <p v-if="!isAdmin && !profileReady && sharedWindows.length" class="daily-leave-muted">
        请先完善个人资料，才能使用共享活动生成请假条。
      </p>
    </section>
  </div>
</template>

<style scoped>
.daily-leave-page { min-width: 0; max-width: 100%; }
.daily-leave-section { min-width: 0; margin-top: 24px; }
.daily-leave-section:first-child { margin-top: 0; }
.daily-leave-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.daily-leave-heading h2 { margin: 0; font-size: 15px; font-weight: 620; }
.daily-leave-feedback { margin: 0 0 12px; font-size: 13px; overflow-wrap: anywhere; }
.daily-leave-error { color: var(--danger); }
.daily-leave-notice { color: var(--success, #23744b); }
.daily-leave-muted { margin: 7px 0; color: var(--faint); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.daily-leave-list { min-width: 0; border-top: 1px solid var(--line); }
.daily-leave-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; min-width: 0; padding: 11px 0; border-bottom: 1px solid var(--line); }
.daily-leave-main { display: grid; gap: 4px; min-width: 0; }
.daily-leave-main strong { font-size: 14px; font-weight: 560; overflow-wrap: anywhere; }
.daily-leave-main span { font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
.daily-leave-main small { color: var(--faint); font-size: 12px; overflow-wrap: anywhere; }
.daily-leave-actions { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.daily-leave-actions button { padding: 2px 0; white-space: nowrap; }
.daily-leave-self-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px 13px; max-width: 720px; }
.daily-leave-self-form label, .daily-leave-create-form label { display: grid; min-width: 0; gap: 5px; color: var(--muted); font-size: 12px; }
.daily-leave-self-form input, .daily-leave-create-form input { box-sizing: border-box; width: 100%; min-width: 0; }
.daily-leave-self-actions { display: flex; align-items: center; gap: 8px; grid-column: 1 / -1; }
.daily-leave-create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px 13px; max-width: 720px; margin-top: 12px; }
.daily-leave-title-field { grid-column: 1 / -1; }
.daily-leave-submit { justify-self: start; }
.daily-leave-link { display: flex; flex-wrap: wrap; gap: 4px 12px; min-width: 0; align-items: baseline; }
.daily-leave-link a { color: var(--secondary); font-size: 12px; overflow-wrap: anywhere; }
.daily-leave-link button { padding: 1px 0; white-space: nowrap; }
@media (max-width: 520px) {
  .daily-leave-row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 7px; }
  .daily-leave-actions { justify-content: flex-start; flex-wrap: wrap; }
  .daily-leave-self-form, .daily-leave-create-form { grid-template-columns: minmax(0, 1fr); }
  .daily-leave-title-field, .daily-leave-self-actions { grid-column: auto; }
}
</style>
