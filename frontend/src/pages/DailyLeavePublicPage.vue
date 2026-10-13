<script setup lang="ts">
import { onMounted, ref } from "vue"

import { ApiError, api } from "../api"
import ActionMenu from "../components/ActionMenu.vue"
import CollegeSelect from "../components/CollegeSelect.vue"
import type { CollegeOption, DailyLeavePublicWindow } from "../types"

const props = defineProps<{ token: string }>()
const windowInfo = ref<DailyLeavePublicWindow | null>(null)
const colleges = ref<CollegeOption[]>([])
const loading = ref(true)
const saving = ref(false)
const downloaded = ref(false)
const error = ref("")
const readyDownload = ref<{ download_url: string; filename: string } | null>(null)
const fieldErrors = ref<Record<string, string>>({})
const draft = ref({ name: "", student_id: "", college: "" })
const submissionCredential = ref<{ token: string; studentId: string; value: string } | null>(null)

function dateTime(value: string) {
  return value.slice(0, 16).replace("T", " ")
}

function messageOf(reason: unknown) {
  if (reason instanceof TypeError) {
    return "网络请求未能完成。请检查网络后重试；已提交的记录只能通过首次下载凭证访问，凭证遗失请联系活动管理员核验身份。"
  }
  return reason instanceof Error ? reason.message : "操作失败"
}

function newDownloadCredential() {
  if (!window.crypto?.getRandomValues) {
    throw new Error("此浏览器无法安全生成下载凭证，请使用其他浏览器或联系活动管理员。")
  }
  const bytes = window.crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "")
}

function getDownloadCredential(token: string, studentId: string) {
  if (submissionCredential.value?.token === token && submissionCredential.value.studentId === studentId) {
    return submissionCredential.value.value
  }
  const credential = newDownloadCredential()
  submissionCredential.value = { token, studentId, value: credential }
  return credential
}

function downloadUrlFor(file: { download_url: string; filename: string }, offline: boolean) {
  const url = new URL(file.download_url, window.location.origin)
  if (offline) url.searchParams.set("offline", "true")
  else url.searchParams.delete("offline")
  return `${url.pathname}${url.search}`
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

function setFieldError(field: string, message: string) {
  fieldErrors.value = { ...fieldErrors.value, [field]: message }
}

function clearFieldError(field: string) {
  const next = { ...fieldErrors.value }
  delete next[field]
  fieldErrors.value = next
}

async function load() {
  loading.value = true
  try {
    const [eventInfo, options] = await Promise.all([
      api.publicDailyLeaveWindow(props.token),
      api.colleges(),
    ])
    windowInfo.value = eventInfo
    colleges.value = options
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    loading.value = false
  }
}

async function generate(offline = false) {
  if (saving.value) return
  error.value = ""
  fieldErrors.value = {}
  if (readyDownload.value) {
    readyDownload.value = {
      ...readyDownload.value,
      download_url: downloadUrlFor(readyDownload.value, offline),
    }
    try {
      requestNativeDownload(readyDownload.value.download_url)
    } catch {
      error.value = "文件请求未能启动，请点击下方下载链接继续。"
    }
    return
  }
  const name = draft.value.name.trim()
  const studentId = draft.value.student_id.trim()
  if (name.length < 2 || name.length > 50) setFieldError("name", "姓名长度需为 2–50 个字符")
  if (!/^[0-9]{8}$/.test(studentId)) setFieldError("student_id", "学号必须是 8 位数字")
  if (!draft.value.college) setFieldError("college", "请选择所属学院")
  if (Object.keys(fieldErrors.value).length) return

  saving.value = true
  try {
    const downloadCredential = getDownloadCredential(props.token, studentId)
    const file = await api.generatePublicDailyLeaveDocument(props.token, {
      name,
      student_id: studentId,
      college: draft.value.college,
      download_credential: downloadCredential,
    }, offline)
    readyDownload.value = { ...file, download_url: downloadUrlFor(file, offline) }
    downloaded.value = true
    requestNativeDownload(readyDownload.value.download_url)
  } catch (reason) {
    if (reason instanceof ApiError && reason.field) setFieldError(reason.field, reason.message)
    else error.value = messageOf(reason)
  } finally {
    saving.value = false
  }
}

function onMenuAction(action: string) {
  if (action === "offline") void generate(true)
}

onMounted(load)
</script>

<template>
  <section class="daily-leave-public-form">
    <p class="brand">TARS BASE</p>
    <template v-if="loading">
      <h1>生成日常请假条</h1>
      <p class="daily-public-muted" role="status">正在读取共享活动时间…</p>
    </template>
    <template v-else-if="windowInfo">
      <span class="daily-public-kicker">共享活动</span>
      <h1>生成日常请假条</h1>
      <dl class="daily-public-facts">
        <div><dt>请假时间</dt><dd>{{ dateTime(windowInfo.start_at) }} 至 {{ dateTime(windowInfo.end_at) }}</dd></div>
      </dl>
      <template>
        <p v-if="windowInfo.accepting_participants" class="daily-public-hint">填写本人信息后即可下载个人请假条。时间固定，不能修改。</p>
        <p v-else class="daily-public-hint">此活动已关闭或截止，不能新增报名。若此前已提交，可在本浏览器仍保留下载凭证时恢复下载；凭证遗失请联系活动管理员核验身份。</p>
        <p v-if="error" class="daily-public-error" role="alert">{{ error }}</p>
        <p v-if="readyDownload" class="daily-public-muted" role="status">
          报名已保存，已向浏览器发起请假条文件请求。请检查下载列表或文件管理器确认保存；若未看到文件，
          <a :href="readyDownload.download_url" referrerpolicy="no-referrer">点击此处重新下载</a>。
        </p>
        <form @submit.prevent="generate(false)">
          <label>
            姓名
            <input v-model="draft.name" autocomplete="name" maxlength="50" required :aria-invalid="Boolean(fieldErrors.name)" @input="clearFieldError('name')" />
            <small v-if="fieldErrors.name" class="daily-public-error">{{ fieldErrors.name }}</small>
          </label>
          <label>
            学号
            <input v-model="draft.student_id" inputmode="numeric" autocomplete="off" maxlength="8" required :aria-invalid="Boolean(fieldErrors.student_id)" @input="clearFieldError('student_id')" />
            <small v-if="fieldErrors.student_id" class="daily-public-error">{{ fieldErrors.student_id }}</small>
          </label>
          <label>
            所属学院
            <CollegeSelect
              v-model="draft.college"
              :options="colleges"
              required
              :invalid="Boolean(fieldErrors.college)"
              @change="clearFieldError('college')"
            />
            <small v-if="fieldErrors.college" class="daily-public-error">{{ fieldErrors.college }}</small>
          </label>
          <div class="daily-public-actions">
            <button class="primary" type="submit" :disabled="saving">{{ saving ? "正在准备文件…" : downloaded ? "重新下载请假条" : windowInfo.accepting_participants ? "生成并下载请假条" : "恢复已提交材料" }}</button>
            <ActionMenu
              id="daily-public-document"
              aria-label="其他下载选项"
              :disabled="saving"
              :actions="[{ key: 'offline', label: '下载线下签章版' }]"
              @select="onMenuAction"
            />
          </div>
        </form>
        <p v-if="downloaded" class="daily-public-muted">报名记录已保存；重复下载不会新建记录。凭证遗失无法仅凭姓名或学号找回，请联系活动管理员核验身份。</p>
      </template>
    </template>
    <template v-else>
      <span class="daily-public-kicker">BASE / DAILY LEAVE</span>
      <h1>共享活动链接已失效</h1>
      <p class="daily-public-error" role="alert">{{ error || "临时链接无效或活动已结束。" }}</p>
    </template>
  </section>
</template>

<style scoped>
.daily-leave-public-form { box-sizing: border-box; width: 100%; min-width: 0; }
.daily-leave-public-form .brand { margin: 0 0 24px; color: var(--text); font-weight: 650; letter-spacing: .08em; }
.daily-public-kicker { color: var(--faint); font-size: 12px; }
.daily-leave-public-form h1 { margin-top: 5px; overflow-wrap: anywhere; }
.daily-public-muted, .daily-public-hint { color: var(--muted); font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
.daily-public-error { color: var(--danger); font-size: 12px; }
.daily-public-facts { margin: 16px 0; }
.daily-public-facts > div { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
.daily-public-facts dt { color: var(--muted); }
.daily-public-facts dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.daily-leave-public-form form { display: grid; gap: 15px; margin-top: 20px; }
.daily-leave-public-form label { min-width: 0; }
.daily-leave-public-form input, .daily-leave-public-form select { box-sizing: border-box; width: 100%; min-width: 0; }
.daily-leave-public-form small { display: block; margin-top: 4px; }
.daily-public-actions { display: flex; align-items: center; gap: 8px; min-width: 0; }
.daily-public-actions .primary { min-width: 0; }
@media (max-width: 380px) { .daily-public-actions { align-items: flex-start; flex-direction: column; } }
</style>
