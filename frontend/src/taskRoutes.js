export function parseTaskEditorRoute(path) {
  if (path === "/tasks/new") return { kind: "new-task" }

  const childMatch = path.match(/^\/tasks\/(\d+)\/new-child$/)
  if (childMatch) return { kind: "new-child", parentId: Number(childMatch[1]) }

  const editMatch = path.match(/^\/tasks\/(\d+)\/edit$/)
  if (editMatch) return { kind: "edit", taskId: Number(editMatch[1]) }

  return null
}

export function taskEditorCancelPath(route) {
  if (!route) return "/tasks"
  if (route.kind === "new-task") return "/tasks"
  if (route.kind === "new-child") return `/tasks/${route.parentId}`
  return `/tasks/${route.taskId}`
}

export function taskEditorSuccessPath(route, createdTaskId = null) {
  if (!route) return "/tasks"
  if (route.kind === "new-task") return createdTaskId ? `/tasks/${createdTaskId}` : "/tasks"
  if (route.kind === "new-child") return `/tasks/${route.parentId}`
  return `/tasks/${route.taskId}`
}

export function taskEditorTitle(route, isChildEdit = false) {
  if (!route) return ""
  if (route.kind === "new-task") return "新建独立任务"
  if (route.kind === "new-child") return "添加分工"
  return isChildEdit ? "编辑分工" : "编辑事项"
}
