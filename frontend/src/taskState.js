export function isIndependentTask(task) {
  return task.kind === "task" && task.parent_id === null
}

export function taskMatchesView(task, view, memberId) {
  if (view === "all") return true
  if (view === "claimable") {
    return task.owner === null && task.owner_claimable && task.status !== "done"
  }
  return task.owner?.id === memberId || task.collaborators.some((member) => member.id === memberId)
}

export function claimableTask(task) {
  return task.owner === null && task.owner_claimable && task.status !== "done"
}

export function tasksForRoot(tasks, rootId, view, memberId) {
  return tasks.filter((task) => task.parent_id === rootId && taskMatchesView(task, view, memberId))
}

export function rootsForView(tasks, view, memberId) {
  const matched = tasks.filter((task) => taskMatchesView(task, view, memberId))
  const relevantRootIds = new Set(
    matched.filter((task) => task.parent_id !== null).map((task) => task.parent_id),
  )
  return tasks.filter(
    (task) => task.parent_id === null && (taskMatchesView(task, view, memberId) || relevantRootIds.has(task.id)),
  )
}

export function deriveRootStatus(children) {
  if (!children.length || children.every((task) => task.status === "todo")) return "todo"
  if (children.every((task) => task.status === "done")) return "done"
  return "doing"
}

export function patchTaskCollection(current, updated, view, memberId, hasCompleteChildren = false, parentContext = null) {
  const next = current.filter((task) => task.id !== updated.id)
  if (taskMatchesView(updated, view, memberId)) next.push(updated)

  if (updated.parent_id !== null && taskMatchesView(updated, view, memberId)) {
    const hasParent = next.some((task) => task.id === updated.parent_id && task.parent_id === null)
    const cachedParent = current.find((task) => task.id === updated.parent_id && task.parent_id === null)
      ?? parentContext
    if (!hasParent && cachedParent) next.push(cachedParent)
  } else if (updated.parent_id === null) {
    const hasRelevantChildren = next.some(
      (task) => task.parent_id === updated.id && taskMatchesView(task, view, memberId),
    )
    if (hasRelevantChildren && !next.some((task) => task.id === updated.id)) next.push(updated)
  }

  if (hasCompleteChildren && updated.parent_id !== null) {
    const rootIndex = next.findIndex((task) => task.id === updated.parent_id)
    const children = next.filter((task) => task.parent_id === updated.parent_id)
    if (rootIndex >= 0 && children.length) {
      next[rootIndex] = { ...next[rootIndex], status: deriveRootStatus(children) }
    }
  }

  const relevantRootIds = new Set(
    next
      .filter((task) => task.parent_id !== null && taskMatchesView(task, view, memberId))
      .map((task) => task.parent_id),
  )
  return next
    .filter((task) => task.parent_id !== null || taskMatchesView(task, view, memberId) || relevantRootIds.has(task.id))
    .sort(compareTaskDeadlines)
}

export function setPendingTaskAction(current, taskId, action) {
  const next = new Map(current)
  if (action === null) next.delete(taskId)
  else next.set(taskId, action)
  return next
}

export function prependUniqueActivity(current, activity) {
  return [activity, ...current.filter((entry) => entry.id !== activity.id)]
}

export function mergeRecentActivities(current, recent) {
  const byId = new Map([...recent, ...current].map((activity) => [activity.id, activity]))
  return [...byId.values()].sort((left, right) => right.id - left.id)
}

export function compareTaskDeadlines(left, right) {
  const leftHasDeadline = Boolean(left.deadline)
  const rightHasDeadline = Boolean(right.deadline)
  if (leftHasDeadline !== rightHasDeadline) return leftHasDeadline ? -1 : 1
  if (!leftHasDeadline) return left.id - right.id
  return new Date(left.deadline).getTime() - new Date(right.deadline).getTime() || left.id - right.id
}
