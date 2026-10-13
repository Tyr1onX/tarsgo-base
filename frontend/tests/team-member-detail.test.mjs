import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"

const team = await readFile(new URL("../src/pages/TeamPage.vue", import.meta.url), "utf8")
const detail = await readFile(new URL("../src/pages/MemberDetailPage.vue", import.meta.url), "utf8")
const app = await readFile(new URL("../src/App.vue", import.meta.url), "utf8")
const css = await readFile(new URL("../src/style.css", import.meta.url), "utf8")
const api = await readFile(new URL("../src/api.ts", import.meta.url), "utf8")
const types = await readFile(new URL("../src/types.ts", import.meta.url), "utf8")

const memberList = team.slice(team.indexOf('<div class="member-list">'), team.lastIndexOf("</section>"))

// Team keeps one shared registration control and a browse-first member list.
assert.ok(team.includes("<h2>团队注册</h2>"))
assert.ok(team.includes("开启 72 小时注册"))
assert.ok(team.includes("registrationWindow"))
assert.ok(team.includes("registrationPath"))
assert.ok(team.includes("复制注册链接"))
assert.ok(team.includes("提前关闭"))
assert.ok(team.includes("emit('openRegistration')"))
assert.ok(team.includes("emit('closeRegistration')"))
assert.ok(team.includes("emit('copyRegistration')"))
assert.ok(!team.includes("<h2>邀请成员</h2>"))
assert.ok(!team.includes("创建邀请"))

assert.ok(memberList.includes("member.name"))
assert.ok(memberList.includes("member.email"))
assert.ok(memberList.includes("groupLabel(member)"))
assert.ok(memberList.includes("roleLabels[member.role]"))
assert.ok(memberList.includes("memberStatusLabel(member)"))
assert.ok(memberList.includes("学号 ${member.student_id}"))
assert.ok(memberList.includes("学号未填写"))
assert.ok(memberList.includes("emit('navigate', `/team/${member.id}`)"))
assert.ok(memberList.includes('class="team-member-link"'))
assert.ok(memberList.includes('class="team-member-chevron"'))
assert.ok(!memberList.includes(">编辑</button>"))
assert.ok(!memberList.includes("<input"))
assert.doesNotMatch(memberList, />\s*(?:停用|恢复|生成邀请)\s*</)

assert.ok(team.includes('const filteredMembers = computed(() =>'))
assert.ok(team.includes('const enabledMembers = computed(() => filteredMembers.value.filter((member) => member.status !== "disabled"))'))
assert.ok(team.includes('const allDisabledMembers = computed(() => props.members.filter((member) => member.status === "disabled"))'))
assert.ok(team.includes('const disabledMembers = computed(() => filteredMembers.value.filter((member) => member.status === "disabled"))'))
assert.ok(team.includes('v-for="member in enabledMembers"'))
assert.ok(team.includes('v-if="allDisabledMembers.length" class="team-disabled-members"'))
assert.ok(team.includes("已停用成员（{{ allDisabledMembers.length }}）"))
assert.ok(team.includes('v-for="member in disabledMembers"'))
assert.ok(team.includes('member.status === "disabled") return "已停用"'))
assert.doesNotMatch(team, /return member\.status/)

// Member detail remains an admin-only route and provides audited identity correction.
assert.ok(app.includes('const MemberDetailPage = defineLazyPage(() => import("./pages/MemberDetailPage.vue"))'))
assert.ok(app.includes("const teamMemberDetailId = computed"))
assert.ok(app.includes('const match = path.value.match(/^\\/team\\/(\\d+)$/)'))
const detailLoader = app.slice(
  app.indexOf("else if (teamMemberDetailId.value !== null)"),
  app.indexOf('else if (routePath === "/team")'),
)
assert.ok(detailLoader.includes("if (!isAdmin.value)"))
assert.ok(detailLoader.includes('navigate("/")'))
assert.ok(detailLoader.includes("const [teamMembers] = await Promise.all([api.members(), ensureCollegeOptions()])"))
assert.ok(detailLoader.includes("members.value = teamMembers"))

assert.ok(detail.includes('v-model="nameDraft"'))
assert.ok(detail.includes("姓名与学号修改记录"))
assert.ok(detail.includes("identityAudit"))
assert.ok(api.includes("memberIdentityAudit"))
assert.ok(detail.includes("member.name"))
assert.ok(detail.includes("<dt>邮箱</dt>"))
assert.ok(detail.includes("member.email"))
assert.ok(detail.includes("<dt>系统权限</dt>"))
assert.ok(detail.includes("roleLabels[member.role]"))
assert.ok(detail.includes("<dt>状态</dt>"))
assert.ok(detail.includes("memberStatusLabel(member)"))
assert.ok(detail.includes('member.status === "disabled") return "已停用"'))
assert.ok(!detail.includes("<dd>{{ member.status }}</dd>"))
assert.ok(detail.includes('v-model="studentIdDraft"'))
assert.ok(detail.includes('v-model="teamGroupDraft"'))
assert.ok(detail.includes("<span>所属组别</span>"))
assert.ok(detail.includes('v-for="(label, code) in groupLabels"'))
assert.ok(detail.includes('emit("updateProfile"'))
assert.ok(app.includes('@update-profile="updateMemberProfile"'))
assert.ok(api.includes("updateMemberProfile: (memberId: number, payload: MemberProfilePayload)"))
assert.ok(api.includes("/api/members/${memberId}/profile"))
assert.ok(detail.includes('v-model="collegeDraft"'))
assert.ok(detail.includes('v-model="teamMembershipDraft"'))
assert.ok(detail.includes('<CollegeSelect'))
assert.ok(detail.includes(':options="collegeOptions"'))
assert.ok(detail.includes('clearable'))
assert.ok(detail.includes('v-for="(label, code) in membershipLabels"'))
assert.ok(app.includes('@clear-profile-error="clearMemberProfileFieldError(teamMemberDetail.id, $event)"'))

// Existing invited accounts keep their legacy activation path only in member detail.
assert.ok(detail.includes("member.status === 'invited'"))
assert.ok(detail.includes("邀请尚未完成"))
assert.ok(detail.includes("重新生成邀请"))
assert.ok(detail.includes("复制邀请链接"))
assert.ok(app.includes('@regenerate-invite="regenerateInvite"'))

// Role and task-member privacy are both reduced to the intended surface.
assert.ok(types.includes('export type Role = "admin" | "member"'))
assert.ok(!types.includes('"manager"'))
assert.ok(!app.includes("isManager"))
assert.ok(!app.includes("任务管理员"))
const memberSummary = types.slice(types.indexOf("export interface MemberSummary"), types.indexOf("export interface Task"))
assert.ok(!memberSummary.includes("student_id"))
assert.ok(!memberSummary.includes("team_group"))
const memberType = types.slice(types.indexOf("export interface Member {"), types.indexOf("export interface MemberSummary"))
assert.ok(memberType.includes("student_id: string | null"))
assert.ok(memberType.includes("team_group: TeamGroup | null"))

// Fixed group labels are centralized in the app, not free-form member text.
for (const label of ["电控组", "机械组", "视觉组", "AI组", "运营组"]) {
  assert.ok(app.includes(label))
}

// Responsive member/profile layouts do not introduce a wide minimum viewport.
assert.ok(team.includes("@media (max-width: 520px)"))
assert.ok(team.includes("overflow-wrap: anywhere"))
assert.ok(detail.includes("@media (max-width: 520px)"))
assert.ok(detail.includes("grid-template-columns: minmax(78px, 96px) minmax(0, 1fr)"))
assert.ok(detail.includes(".member-profile-form"))
assert.match(css, /@media \(max-width: 1000px\)[\s\S]*?\.member-profile-form\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s)
assert.doesNotMatch(team + detail, /width:\s*100vw/)
assert.doesNotMatch(team + detail, /min-width:\s*(?:4\d\d|[5-9]\d\d|\d{4,})px/)

console.log("Team member detail and group profile frontend tests passed")
