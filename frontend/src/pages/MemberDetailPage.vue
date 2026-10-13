<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { api } from "../api"
import CollegeSelect from "../components/CollegeSelect.vue"
import type {
  CollegeOption,
  InviteResult,
  Member,
  MemberIdentityAudit,
  MemberProfilePayload,
  Role,
  TeamGroup,
  TeamMembership,
} from "../types"

const props = defineProps<{
  member: Member
  currentUserId: number | null
  latestInvite: InviteResult | null
  roleLabels: Record<Role, string>
  groupLabels: Record<TeamGroup, string>
  collegeOptions: CollegeOption[]
  membershipLabels: Record<TeamMembership, string>
  fieldErrors: Record<string, string>
  formatDate: (value: string) => string
  profileSaving: boolean
}>()

const emit = defineEmits<{
  regenerateInvite: [memberId: number]
  disableMember: [memberId: number]
  enableMember: [memberId: number]
  updateProfile: [payload: { memberId: number } & MemberProfilePayload]
  clearProfileError: [field: string]
  copyInvite: []
  navigate: [path: string]
}>()

const studentIdDraft = ref("")
const nameDraft = ref("")
const teamGroupDraft = ref<TeamGroup | "">("")
const collegeDraft = ref("")
const teamMembershipDraft = ref<TeamMembership | "">("")
const localFieldErrors = ref<Record<string, string>>({})
const identityAudit = ref<MemberIdentityAudit[]>([])
const identityAuditError = ref("")

async function loadIdentityAudit(memberId: number) {
  identityAuditError.value = ""
  try {
    identityAudit.value = await api.memberIdentityAudit(memberId)
  } catch (reason) {
    identityAudit.value = []
    identityAuditError.value = reason instanceof Error ? reason.message : "身份修改记录加载失败"
  }
}

watch(
  () => props.member,
  (member) => {
    nameDraft.value = member.name
    studentIdDraft.value = member.student_id ?? ""
    teamGroupDraft.value = member.team_group ?? ""
    collegeDraft.value = member.college ?? ""
    teamMembershipDraft.value = member.team_membership ?? ""
    localFieldErrors.value = {}
    void loadIdentityAudit(member.id)
  },
  { immediate: true },
)

const normalizedStudentId = computed(() => studentIdDraft.value.trim())
const savedStudentId = computed(() => props.member.student_id ?? "")
const normalizedName = computed(() => nameDraft.value.trim())
const profileChanged = computed(
  () =>
    normalizedName.value !== props.member.name ||
    normalizedStudentId.value !== savedStudentId.value ||
    teamGroupDraft.value !== (props.member.team_group ?? "") ||
    collegeDraft.value !== (props.member.college ?? "") ||
    teamMembershipDraft.value !== (props.member.team_membership ?? ""),
)
const currentInvite = computed(() =>
  props.latestInvite?.member.id === props.member.id ? props.latestInvite : null,
)

function memberStatusLabel(member: Member) {
  if (member.status === "invited") return "邀请中"
  if (member.status === "disabled") return "已停用"
  return "正常"
}

function saveProfile() {
  if (!profileChanged.value || props.profileSaving) return
  localFieldErrors.value = {}
  if (Array.from(normalizedName.value).length < 2 || Array.from(normalizedName.value).length > 50) {
    localFieldErrors.value = { name: "姓名长度需为 2–50 个字符" }
    return
  }
  if (normalizedStudentId.value && !/^\d{8}$/.test(normalizedStudentId.value)) {
    localFieldErrors.value = { student_id: "学号必须是 8 位数字" }
    return
  }
  if (collegeDraft.value && !props.collegeOptions.some((college) => college.code === collegeDraft.value)) {
    localFieldErrors.value = { college: "请选择有效学院" }
    return
  }
  emit("updateProfile", {
    memberId: props.member.id,
    name: normalizedName.value,
    student_id: normalizedStudentId.value || null,
    team_group: teamGroupDraft.value || null,
    college: collegeDraft.value || null,
    team_membership: teamMembershipDraft.value || null,
  })
}

function fieldError(field: string) {
  return localFieldErrors.value[field] ?? props.fieldErrors[field]
}

function clearProfileError(field: string) {
  if (localFieldErrors.value[field]) {
    const next = { ...localFieldErrors.value }
    delete next[field]
    localFieldErrors.value = next
  }
  emit("clearProfileError", field)
}
</script>

<template>
  <button class="member-detail-back" type="button" @click="emit('navigate', '/team')">← 返回团队</button>

  <header class="member-detail-heading">
    <h1>{{ member.name }}</h1>
    <span>成员资料</span>
  </header>

  <section class="member-detail-section">
    <h2>基本信息</h2>
    <dl class="member-detail-fields">
      <div>
        <dt>邮箱</dt>
        <dd>{{ member.email }}</dd>
      </div>
      <div>
        <dt>系统权限</dt>
        <dd>{{ roleLabels[member.role] }}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>{{ memberStatusLabel(member) }}</dd>
      </div>
    </dl>
  </section>

  <section class="member-detail-section">
    <h2>学校 / 团队资料</h2>
    <form class="member-profile-form" @submit.prevent="saveProfile">
      <label>
        <span>姓名</span>
        <input v-model="nameDraft" maxlength="50" autocomplete="name" @input="clearProfileError('name')" />
        <small v-if="fieldError('name')" class="field-error">{{ fieldError('name') }}</small>
      </label>
      <label>
        <span>学号</span>
        <input
          v-model="studentIdDraft"
          maxlength="8"
          inputmode="numeric"
          autocomplete="off"
          placeholder="未填写学号"
          @input="clearProfileError('student_id')"
        />
        <small v-if="fieldError('student_id')" class="field-error">{{ fieldError('student_id') }}</small>
      </label>
      <label>
        <span>学院</span>
        <CollegeSelect
          v-model="collegeDraft"
          :options="collegeOptions"
          clearable
          placeholder="可留空，搜索学院"
          :invalid="Boolean(fieldError('college'))"
          @change="clearProfileError('college')"
        />
        <small v-if="fieldError('college')" class="field-error">{{ fieldError('college') }}</small>
      </label>
      <label>
        <span>所属组别</span>
        <select v-model="teamGroupDraft">
          <option value="">未填写</option>
          <option v-for="(label, code) in groupLabels" :key="code" :value="code">{{ label }}</option>
        </select>
      </label>
      <label>
        <span>队内身份</span>
        <select v-model="teamMembershipDraft" @change="clearProfileError('team_membership')">
          <option value="">未填写</option>
          <option v-for="(label, code) in membershipLabels" :key="code" :value="code">{{ label }}</option>
        </select>
        <small v-if="fieldError('team_membership')" class="field-error">{{ fieldError('team_membership') }}</small>
      </label>
      <button
        class="primary member-profile-save"
        type="submit"
        :disabled="!profileChanged || profileSaving"
      >
        {{ profileSaving ? "保存中…" : "保存修改" }}
      </button>
    </form>
  </section>

  <section class="member-detail-section">
    <h2>姓名与学号修改记录</h2>
    <p v-if="identityAuditError" class="field-error" role="alert">{{ identityAuditError }}</p>
    <p v-else-if="identityAudit.length === 0" class="member-account-note">暂无身份信息修改记录</p>
    <ul v-else class="member-identity-audit">
      <li v-for="item in identityAudit" :key="item.id">
        <strong>{{ item.field === 'name' ? '姓名' : '学号' }}</strong>
        <span>{{ item.old_value || '空' }} → {{ item.new_value || '空' }}</span>
        <small>{{ formatDate(item.changed_at) }} · 管理员 ID {{ item.admin_id ?? '已删除' }}</small>
      </li>
    </ul>
  </section>

  <section class="member-detail-section member-account-section">
    <h2>账号操作</h2>

    <template v-if="member.status === 'invited'">
      <p class="member-account-note">邀请尚未完成</p>
      <button type="button" class="member-secondary-action" @click="emit('regenerateInvite', member.id)">
        重新生成邀请
      </button>

      <div v-if="currentInvite" class="member-invite-result">
        <span>邀请有效至 {{ formatDate(currentInvite.expires_at) }}</span>
        <button type="button" @click="emit('copyInvite')">复制邀请链接</button>
      </div>
    </template>

    <button
      v-else-if="member.status === 'active' && member.id !== currentUserId"
      class="member-danger-action"
      type="button"
      @click="emit('disableMember', member.id)"
    >
      停用成员
    </button>

    <p v-else-if="member.status === 'active'" class="member-account-note">
      当前登录账号不能停用自己。
    </p>

    <button
      v-else-if="member.status === 'disabled'"
      class="member-secondary-action"
      type="button"
      @click="emit('enableMember', member.id)"
    >
      恢复成员
    </button>
  </section>
</template>

<style scoped>
.member-detail-back {
  border: 0;
  background: transparent;
  padding: 3px 0;
  color: var(--muted);
}

.member-detail-back:hover {
  color: var(--text);
}

.member-detail-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 10px 0 28px;
}

.member-detail-heading h1 {
  margin: 0;
}

.member-detail-heading span {
  color: var(--faint);
  font-size: 13px;
}

.member-detail-section {
  padding: 20px 0 24px;
  border-top: 1px solid var(--line);
}

.member-detail-section h2 {
  margin: 0 0 14px;
  font-size: 14px;
}

.member-detail-fields {
  margin: 0;
}

.member-detail-fields > div {
  display: grid;
  grid-template-columns: minmax(100px, 150px) minmax(0, 1fr);
  gap: 16px;
  padding: 8px 0;
}

.member-detail-fields dt {
  color: var(--muted);
  font-size: 12.5px;
}

.member-detail-fields dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.member-account-section {
  display: grid;
  justify-items: start;
  gap: 9px;
}

.member-account-section h2 {
  margin-bottom: 5px;
}

.member-account-note {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.member-danger-action,
.member-secondary-action,
.member-invite-result button {
  border: 0;
  background: transparent;
  padding: 4px 0;
}

.member-danger-action {
  color: var(--danger);
}

.member-secondary-action,
.member-invite-result button {
  color: var(--secondary);
}

.member-invite-result {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 14px;
  margin-top: 3px;
  color: var(--muted);
  font-size: 12.5px;
}

.member-identity-audit {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.member-identity-audit li {
  display: grid;
  gap: 3px;
  overflow-wrap: anywhere;
}

.member-identity-audit small { color: var(--muted); }

.member-detail-heading,
.member-detail-fields,
.member-profile-form,
.member-invite-result,
.member-identity-audit {
  min-width: 0;
}

@media (max-width: 520px) {
  .member-detail-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
    margin-bottom: 22px;
  }

  .member-detail-fields > div {
    grid-template-columns: minmax(78px, 96px) minmax(0, 1fr);
    gap: 10px;
  }
}
</style>
