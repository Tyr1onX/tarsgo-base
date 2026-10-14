<script setup lang="ts">
import { onMounted, ref } from "vue"

import { api } from "../api"
import type { AdminLeaveRecord, AdminLeaveRecordType, Member } from "../types"

const props = defineProps<{ currentUser: Member }>()
const emit = defineEmits<{ unreadCount: [count: number] }>()
const records = ref<AdminLeaveRecord[]>([])
const isAdmin = props.currentUser.role === "admin"
const loading = ref(isAdmin)
const error = ref("")
const nameFilter = ref("")
const dateFrom = ref("")
const dateTo = ref("")
const recordType = ref<AdminLeaveRecordType | "">("")
const markingReadId = ref<string | null>(null)

function dateTime(value: string) {
  return value.slice(0, 16).replace("T", " ")
}

function recordTypeLabel(record: AdminLeaveRecord) {
  return record.record_type === "generated" ? "请假条生成记录" : "正式请假申请"
}

function sourceLabel(record: AdminLeaveRecord) {
  if (record.source_type === "self_service") return "个人自助生成"
  if (record.source_type === "shared_activity") return "共享活动生成"
  return "旧版日常申请"
}

function applicationStatusLabel(status: AdminLeaveRecord["application_status"]) {
  if (status === "pending") return "待汇总"
  if (status === "included") return "已纳入汇总"
  if (status === "withdrawn") return "已撤回"
  return ""
}

function summaryStatusLabel(status: AdminLeaveRecord["summary_status"]) {
  if (status === "ready") return "待下载"
  if (status === "awaiting_return") return "回传处理中"
  if (status === "completed") return "已完成"
  if (status === "cancelled") return "已取消"
  return ""
}

async function loadRecords() {
  if (!isAdmin) return
  loading.value = true
  error.value = ""
  try {
    const [nextRecords, updates] = await Promise.all([
      api.adminLeaveRecords({
        name: nameFilter.value,
        date_from: dateFrom.value,
        date_to: dateTo.value,
        record_type: recordType.value || undefined,
      }),
      api.adminUpdateUnreadCount().catch(() => null),
    ])
    records.value = nextRecords
    if (updates) emit("unreadCount", updates.unread_count)
  } catch (reason) {
    records.value = []
    error.value = reason instanceof Error ? reason.message : "请假记录加载失败"
  } finally {
    loading.value = false
  }
}

async function markRead(record: AdminLeaveRecord) {
  if (!record.is_unread || !record.update_event_ids.length || markingReadId.value) return
  markingReadId.value = record.id
  error.value = ""
  try {
    const result = await api.markAdminUpdatesRead(record.update_event_ids)
    records.value = records.value.map((item) => item.id === record.id ? { ...item, is_unread: false } : item)
    emit("unreadCount", result.unread_count)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "标记已读失败"
  } finally {
    markingReadId.value = null
  }
}

function requestDescription(requestStage: "prepare" | "download", requestType: "first_generation" | "repeat_download") {
  if (requestStage === "prepare") {
    return requestType === "first_generation" ? "首次生成准备" : "重复准备请求"
  }
  return requestType === "first_generation" ? "首次文件请求" : "重复下载请求"
}

function requestStageLabel(requestStage: "prepare" | "download") {
  return requestStage === "prepare" ? "POST 准备" : "GET 文件"
}

function applyFilters() {
  if (dateFrom.value && dateTo.value && dateFrom.value > dateTo.value) {
    records.value = []
    error.value = "开始日期不能晚于结束日期"
    return
  }
  void loadRecords()
}

function resetFilters() {
  nameFilter.value = ""
  dateFrom.value = ""
  dateTo.value = ""
  recordType.value = ""
  void loadRecords()
}

onMounted(() => {
  void loadRecords()
})
</script>

<template>
  <section class="legacy-leave-history" aria-label="成员请假记录">
    <form class="leave-record-filters" @submit.prevent="applyFilters">
      <label>
        <span>成员姓名</span>
        <input v-model="nameFilter" type="search" maxlength="100" placeholder="搜索姓名" />
      </label>
      <label>
        <span>请假日期从</span>
        <input v-model="dateFrom" type="date" />
      </label>
      <label>
        <span>请假日期到</span>
        <input v-model="dateTo" type="date" />
      </label>
      <label>
        <span>记录类型</span>
        <select v-model="recordType">
          <option value="">全部类型</option>
          <option value="generated">请假条生成记录</option>
          <option value="formal_application">正式请假申请</option>
        </select>
      </label>
      <div class="leave-record-filter-actions">
        <button class="primary" type="submit" :disabled="loading">{{ loading ? "查询中…" : "筛选" }}</button>
        <button class="text-action" type="button" :disabled="loading" @click="resetFilters">重置</button>
      </div>
    </form>

    <p v-if="error" class="leave-record-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="leave-record-muted" role="status">正在加载请假记录…</p>
    <p v-else-if="!records.length" class="leave-record-muted">没有符合条件的请假记录。</p>
    <p v-else class="leave-record-muted">共 {{ records.length }} 条记录</p>

    <div v-if="!loading && records.length" class="leave-record-list">
      <article v-for="record in records" :key="record.id" class="leave-record-card">
        <div class="leave-record-heading">
          <strong>{{ record.name }}</strong>
          <span class="leave-record-student-id">学号 {{ record.student_id }}</span>
        </div>
        <div class="leave-record-tags">
          <span class="leave-record-type">{{ recordTypeLabel(record) }}</span>
          <span>{{ sourceLabel(record) }}</span>
          <span v-if="record.is_unread" class="leave-record-unread">新事项</span>
        </div>
        <button
          v-if="record.is_unread"
          class="leave-record-mark-read"
          type="button"
          :disabled="markingReadId !== null"
          @click="markRead(record)"
        >{{ markingReadId === record.id ? "保存中…" : "标记已读" }}</button>
        <dl class="leave-record-details">
          <div class="leave-record-primary-detail">
            <dt>请假时间</dt>
            <dd>{{ dateTime(record.start_at) }} 至 {{ dateTime(record.end_at) }}</dd>
          </div>
          <div class="leave-record-primary-detail">
            <dt>{{ record.record_type === "generated" ? "生成时间" : "提交时间" }}</dt>
            <dd>{{ dateTime(record.recorded_at) }}</dd>
          </div>
          <div v-if="record.record_type === 'generated' && record.generation_count > 1">
            <dt>重复记录</dt>
            <dd>{{ record.generation_count - 1 }} 条</dd>
          </div>
          <div v-if="record.activity_title">
            <dt>{{ record.source_type === "shared_activity" ? "关联活动" : "关联旧版汇总" }}</dt>
            <dd>{{ record.activity_title }}</dd>
          </div>
          <div v-if="record.activity_at">
            <dt>汇总时间</dt>
            <dd>{{ dateTime(record.activity_at) }}</dd>
          </div>
          <div v-if="record.application_status">
            <dt>申请状态</dt>
            <dd>{{ applicationStatusLabel(record.application_status) }}</dd>
          </div>
          <div v-if="record.summary_status">
            <dt>汇总状态</dt>
            <dd>{{ summaryStatusLabel(record.summary_status) }}</dd>
          </div>
        </dl>
        <details v-if="record.record_type === 'generated' && record.document_requests.length" class="leave-record-requests">
          <summary>查看文件请求记录</summary>
          <ul>
            <li v-for="request in record.document_requests" :key="request.id">
              {{ dateTime(request.requested_at) }} · {{ requestStageLabel(request.request_stage) }} ·
              {{ requestDescription(request.request_stage, request.request_type) }} ·
              {{ request.file_version }}{{ request.offline ? "（线下签章版）" : "" }}
            </li>
          </ul>
        </details>
      </article>
    </div>
  </section>
</template>

<style scoped>
.legacy-leave-history { min-width: 0; }
.leave-record-filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px 12px; align-items: end; margin-bottom: 14px; }
.leave-record-filters label { display: grid; min-width: 0; gap: 5px; color: var(--muted); font-size: 12px; }
.leave-record-filters input, .leave-record-filters select { box-sizing: border-box; width: 100%; min-width: 0; }
.leave-record-filter-actions { display: flex; align-items: center; gap: 12px; min-height: 36px; }
.leave-record-filter-actions button { white-space: nowrap; }
.leave-record-muted { margin: 8px 0; color: var(--faint); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.leave-record-error { margin: 8px 0; color: var(--danger); font-size: 12px; }
.leave-record-list { display: grid; gap: 9px; }
.leave-record-card { min-width: 0; padding: 13px 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.leave-record-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 5px 12px; }
.leave-record-heading strong { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.leave-record-student-id { color: var(--muted); font-size: 12px; }
.leave-record-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; color: var(--muted); font-size: 11px; }
.leave-record-tags span { padding: 3px 7px; border-radius: 999px; background: var(--surface-raised, var(--line)); }
.leave-record-tags .leave-record-type { color: var(--text); font-weight: 560; }
.leave-record-tags .leave-record-unread { background: var(--hover); color: var(--danger); font-weight: 650; }
.leave-record-mark-read { margin-top: 9px; padding: 0; border: 0; background: transparent; color: var(--muted); font: inherit; font-size: 12px; cursor: pointer; }
.leave-record-mark-read:disabled { cursor: wait; opacity: .55; }
.leave-record-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 18px; margin: 11px 0 0; }
.leave-record-details div { min-width: 0; }
.leave-record-details dt { margin-bottom: 3px; color: var(--faint); font-size: 11px; }
.leave-record-details dd { margin: 0; color: var(--text); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
.leave-record-details .leave-record-primary-detail dd { font-size: 13px; font-weight: 560; }
.leave-record-requests { margin-top: 10px; color: var(--muted); font-size: 12px; }
.leave-record-requests summary { cursor: pointer; }
.leave-record-requests ul { display: grid; gap: 4px; margin: 7px 0 0; padding-left: 20px; }
@media (max-width: 680px) {
  .leave-record-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 420px) {
  .leave-record-filters { grid-template-columns: minmax(0, 1fr); }
  .leave-record-details { grid-template-columns: minmax(0, 1fr); gap: 8px; }
}
</style>
