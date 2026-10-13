import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"

import { collegeMenuPlacement, filterCollegeOptions, moveCollegeActiveIndex } from "../src/collegeSelect.js"

const read = (path) => readFile(new URL(path, import.meta.url), "utf8")
const [app, memberDetail, campPublic, component, api] = await Promise.all([
  read("../src/App.vue"),
  read("../src/pages/MemberDetailPage.vue"),
  read("../src/pages/CampLeavePublicPage.vue"),
  read("../src/components/CollegeSelect.vue"),
  read("../src/api.ts"),
])

const options = [
  { code: "communication", name: "通信工程学院" },
  { code: "computer", name: "计算机科学与技术学院" },
  { code: "physics", name: "物理学院" },
]
assert.deepEqual(filterCollegeOptions(options, "通信").map((option) => option.name), ["通信工程学院"])
assert.deepEqual(filterCollegeOptions(options, "计算").map((option) => option.name), ["计算机科学与技术学院"])
assert.deepEqual(filterCollegeOptions(options, "  物理 ").map((option) => option.code), ["physics"])
assert.deepEqual(filterCollegeOptions(options, "不存在的学院"), [])

assert.equal(moveCollegeActiveIndex(-1, "down", 3), 0)
assert.equal(moveCollegeActiveIndex(0, "down", 3), 1)
assert.equal(moveCollegeActiveIndex(2, "down", 3), 0)
assert.equal(moveCollegeActiveIndex(-1, "up", 3), 2)
assert.equal(moveCollegeActiveIndex(0, "up", 3), 2)
assert.equal(moveCollegeActiveIndex(0, "down", 0), -1)
assert.deepEqual(collegeMenuPlacement(320, 250, 290), { opensAbove: true, maxHeight: 242 })
assert.deepEqual(collegeMenuPlacement(320, 100, 140), { opensAbove: false, maxHeight: 172 })

assert.match(component, /options: CollegeOption\[\]/)
assert.match(component, /filteredOptions = computed\(\(\) => filterCollegeOptions\(props\.options, query\.value\)\)/)
assert.match(component, /role="combobox"[\s\S]*?aria-autocomplete="list"[\s\S]*?aria-haspopup="listbox"[\s\S]*?:aria-expanded="isOpen"/)
assert.match(component, /@focus="openMenu"/)
assert.match(component, /role="listbox"/)
assert.match(component, /role="option"/)
assert.match(component, /event\.key === "ArrowDown" \|\| event\.key === "ArrowUp"/)
assert.match(component, /event\.key === "Enter" && isOpen\.value[\s\S]*?chooseCollege\(option\)/)
assert.match(component, /event\.key === "Escape" && isOpen\.value[\s\S]*?closeMenu\(\)/)
assert.match(component, /document\.addEventListener\("pointerdown", onOutsidePointer\)/)
assert.match(component, /rootRef\.value\?\.contains\(event\.target as Node\)/)
assert.match(component, /inputRef\.value\?\.focus\(\)/)
assert.match(component, /没有匹配的学院/)
assert.match(component, /function onInput\(event: Event\)[\s\S]*?emit\("update:modelValue", ""\)/)
const chooseCollege = component.match(/function chooseCollege\(option: CollegeOption\) \{([\s\S]*?)\n\}/)?.[1] ?? ""
assert.match(chooseCollege, /emit\("update:modelValue", option\.code\)/)
assert.doesNotMatch(chooseCollege, /emit\("update:modelValue", query\.value\)/)
assert.match(component, /clearable\?: boolean/)
assert.match(component, /max-height: min\(280px, calc\(100dvh - 24px\)\)/)
assert.match(component, /overflow-y: auto/)
assert.match(component, /college-select__menu--above/)
assert.match(component, /const viewportHeight = viewport\?\.height \?\? window\.innerHeight/)
assert.match(component, /window\.visualViewport\?\.addEventListener\("resize", onViewportResize\)/)
assert.match(component, /width: 100%;[\s\S]*?max-width: calc\(100vw - 24px\)/)
assert.doesNotMatch(component, /width:\s*(?:4\d\d|[5-9]\d\d|\d{4,})px/)

assert.equal((app.match(/<CollegeSelect/g) ?? []).length, 3)
assert.match(app, /v-model="registrationCollege"[\s\S]*?:options="collegeOptions"[\s\S]*?required/)
assert.match(app, /collegeOptions\.value\.some\(\(college\) => college\.code === registrationCollege\.value\)/)
assert.match(app, /v-model="collegeDraft"[\s\S]*?:options="collegeOptions"[\s\S]*?clearable/)
assert.match(app, /collegeDraft\.value && !collegeOptions\.value\.some/)
assert.match(app, /college: collegeDraft\.value \|\| null/)
assert.match(app, /placeholder="可留空，搜索学院"/)

assert.match(memberDetail, /v-model="collegeDraft"[\s\S]*?:options="collegeOptions"[\s\S]*?clearable/)
assert.match(memberDetail, /collegeDraft\.value && !props\.collegeOptions\.some/)
assert.match(memberDetail, /college: collegeDraft\.value \|\| null/)
assert.match(memberDetail, /placeholder="可留空，搜索学院"/)
assert.match(campPublic, /v-model="draft\.college"[\s\S]*?:options="colleges"[\s\S]*?required/)
assert.match(campPublic, /if \(!draft\.value\.college\) setFieldError\("college", "请选择所属学院"\)/)
assert.match(campPublic, /college: draft\.value\.college/)
assert.match(api, /college: string \}\) =>/)

console.log("Unified searchable college select, fixed-code selection, required/profile rules, keyboard and mobile behavior passed")
