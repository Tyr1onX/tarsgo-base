const DAY_MS = 24 * 60 * 60 * 1000

export function recentBaseChanges(tasks, relatedTasks, activities, memberId, now = Date.now()) {
  if (!memberId) return []

  const taskById = new Map(tasks.map((task) => [task.id, task]))
  const roots = new Map(tasks.filter((task) => task.parent_id === null).map((task) => [task.id, task]))
  const relatedTaskIdsByRoot = new Map()
  const relatedRootIds = new Set()

  for (const task of relatedTasks) {
    const rootId = task.parent_id ?? task.id
    relatedRootIds.add(rootId)
    if (task.parent_id !== null) {
      const ids = relatedTaskIdsByRoot.get(rootId) ?? new Set()
      ids.add(task.id)
      relatedTaskIdsByRoot.set(rootId, ids)
    }
  }

  const cutoff = now - 30 * DAY_MS
  const entries = []
  const visibleFactsByRoot = new Map()
  const seenFactIds = new Set()

  for (const rootId of relatedRootIds) {
    const root = roots.get(rootId)
    if (!root) continue
    const relatedIds = relatedTaskIdsByRoot.get(rootId) ?? new Set()
    const ownsRoot = root.owner?.id === memberId
    const visibleFacts = []

    for (const fact of root.item_facts ?? []) {
      if (fact.scope === "related" && !ownsRoot && !(fact.related_tasks ?? []).some((task) => relatedIds.has(task.id))) continue
      visibleFacts.push(fact)
      if (seenFactIds.has(fact.id)) continue
      seenFactIds.add(fact.id)
      const timestamp = Date.parse(fact.created_at)
      if (!Number.isFinite(timestamp) || timestamp < cutoff || timestamp > now) continue
      entries.push({
        id: `fact-${fact.id}`,
        root_task_id: rootId,
        context: root.title,
        content: fact.content,
        created_at: fact.created_at,
        priority: 0,
      })
    }
    visibleFactsByRoot.set(rootId, visibleFacts)
  }

  const seenActivityIds = new Set()
  const seenContent = new Set(entries.map((entry) => `${entry.root_task_id}:${entry.content.trim()}`))
  for (const activity of activities) {
    if (seenActivityIds.has(activity.id) || !relatedRootIds.has(activity.root_task_id)) continue
    seenActivityIds.add(activity.id)
    const timestamp = Date.parse(activity.created_at)
    if (!Number.isFinite(timestamp) || timestamp < cutoff || timestamp > now) continue

    const root = roots.get(activity.root_task_id)
    if (!root) continue
    const relatedIds = relatedTaskIdsByRoot.get(activity.root_task_id) ?? new Set()
    const ownsRoot = root.owner?.id === memberId
    const isIndependentRootActivity = root.kind === "task" && activity.task_id === root.id
    if (!ownsRoot && activity.task_id !== null && !relatedIds.has(activity.task_id) && !isIndependentRootActivity) continue
    if ((visibleFactsByRoot.get(activity.root_task_id) ?? []).some((fact) => fact.source_activity_id === activity.id)) continue

    const task = activity.task_id === null ? null : taskById.get(activity.task_id)
    const contentKey = `${activity.root_task_id}:${activity.content.trim()}`
    if (!activity.content.trim() || seenContent.has(contentKey)) continue
    seenContent.add(contentKey)
    entries.push({
      id: `activity-${activity.id}`,
      root_task_id: activity.root_task_id,
      context: task && task.id !== root.id ? `${root.title} · ${task.title}` : root.title,
      content: activity.content,
      created_at: activity.created_at,
      priority: 1,
    })
  }

  return entries
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at) || left.priority - right.priority)
    .slice(0, 3)
}
