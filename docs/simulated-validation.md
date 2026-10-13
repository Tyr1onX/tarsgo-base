# 模拟验证与 AI 评测

## 活动演练

`backend/tests/test_operations_simulation.py` 使用 8 名虚构成员和“模拟校园机器人展示”的 5 项分工。通过真实 HTTP 鉴权及数据库事务覆盖：并发认领、依赖阻塞、禁止成员 PATCH 绕过执行、进展与事项聚合、地点变更、换人继承信息、范围过滤、交接动态、协作者权限、AI 失败不回滚进展、全部完成、重复完成、管理者纠正以及停用后的会话失效。

在隔离测试环境中运行：

```bash
docker compose exec -T api python -m tests.test_operations_simulation
```

脚本结束后删除自己创建的成员及事项，不接触其他工作数据。仍应在测试环境运行，不向生产环境注入模拟活动。报告只包含场景名称和检查结果，不包含密码、邀请链接或会话值。

这些测试证明指定流程能完成，不能证明真实成员使用时间、主观体验或团队持续更新率。

## AI 评测用例

`docs/fixtures/planner-evaluation.json` 包含 20 个脱敏合成场景：简短需求、未知日期、明确否定、独立网络需求、历史污染、当前来源冲突、并行责任、连续责任、交接、采购、素材用途、逐步拆分、无依据建议、附件注入、成员分配、重复提问及独立截止日期。

验证用例完整性不调用模型：

```bash
python3 scripts/evaluate_planner.py
```

真正调用模型时，需在独立测试运行环境配置 provider 及服务端密钥，然后明确使用 `--live`。每个案例只调用一次 provider，最多 20 次；不自动重试，不写任务，也不把生产数据放入案例。

```bash
python3 scripts/evaluate_planner.py --live --output /private/test-results/planner-evaluation-report.json --drafts-directory /private/test-results/drafts
```

这是 provider 输出质量基准，直接使用当前 provider 和 Pydantic schema，刻意不经过发布接口或后端话题清理，因此能发现模型原始输出的问题。它不是生产接口权限测试，不计入服务器数据库中的用户配额；成本计入所用 provider 账号。

自动结果仅检查明确排除内容、无时间背景的日期以及无知识依据的建议。语义质量仍需按每例的 `human_checks` 人工查看草案，记录过度拆分、编造事实、遗漏责任、重复问题和编辑时间。报告只保存检查摘要；可选的 `--drafts-directory` 将纯虚构案例的草案保存到仓库外的私有目录（目录 0700、文件 0600），供人工评审，不加入公共仓库或 CI artifact。prompt 和密钥不保存。

没有真实 provider 配置时，只能声明“用例已准备”和“模拟接口测试通过”，不能声明模型方案质量通过。
