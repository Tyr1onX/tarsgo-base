# 备份与恢复

备份包含 MySQL 全量数据、Alembic 版本和 Knowledge 上传原件。`.env` 和外部服务密钥不在备份中，需由维护者单独安全保管。

## 备份

在仓库根目录运行，显式指定现有 Compose 项目名称和仓库外的目录：

```bash
python3 scripts/backup.py --project YOUR_PROJECT backup --directory /private/backup/tarsgo-2026-10-18
```

脚本会短暂停止运行中的 API，阻止应用同时修改数据库和上传原件；完成或失败后重新启动原来运行的 API。需要能接受短暂停机，并确保此时没有其他程序直接写 MySQL 或知识目录。数据库使用事务快照，知识原件与索引在暂停写入期间备份。

成功后目录包含 `mysql.sql`、`knowledge.tar.gz` 和 `manifest.json`。目录权限为 0700，文件权限为 0600。manifest 记录两个数据文件的 SHA-256 校验值和迁移版本。没有 manifest 的目录代表未完成备份，不能用于恢复。

```bash
python3 scripts/backup.py --project YOUR_PROJECT verify --directory /private/backup/tarsgo-2026-10-18
```

备份本身包含私有团队数据和密码/会话哈希。应复制到受控的异机存储，按团队要求加密；不要上传公共 GitHub 仓库或公开 CI artifacts。校验值检测损坏，不代表来源可信。

## 恢复到全新环境

恢复必须使用独立 Compose 项目、空 MySQL 数据库、空知识目录和停止的 API。建议使用与备份相同的代码版本及数据库版本。不会覆盖已有数据库，也不会自动清空生产数据。

1. 准备目标环境的 `.env`，设置独立 `KNOWLEDGE_STORAGE_HOST_DIR`；不要与现有服务共用目录。若要同时启动 web，使用未占用的端口。
2. 只启动目标数据库：

```bash
docker compose --project-name YOUR_RESTORE_PROJECT --env-file /private/restore.env up -d --wait db
```

3. 构建目标 API 镜像，保持 API 停止：

```bash
docker compose --project-name YOUR_RESTORE_PROJECT --env-file /private/restore.env build api
python3 scripts/backup.py --project YOUR_RESTORE_PROJECT --env-file /private/restore.env restore --directory /private/backup/tarsgo-2026-10-18
```

4. 核对迁移版本、成员/任务/动态/当前信息、Knowledge 原件，再启动目标 API 和 web。
5. 使用恢复后的管理员账号登录，确认事项、负责人、完成结果及知识列表可读。恢复会保留尚未过期的会话；灾难恢复若需要统一重新登录，应另行审查会话失效操作。

恢复失败时，API 保持停止。应检查错误并重新准备一个空目标，不能把部分恢复的数据当作成功结果。

## 自动恢复演练

GitHub Actions 在纯虚构的 CI 数据上调用 `scripts/backup_restore_test.py`。脚本备份源项目，创建全新的 Compose 项目及数据卷，再恢复全部数据。验证所有表中每行内容一致、每个知识原件的内容哈希一致、迁移版本一致、重复恢复到已有数据被拒绝，以及恢复后 API 启动和管理员登录。

仅上传不含原始数据库或文档正文的结果摘要。源项目、生产环境和外部服务凭据不通过恢复演练互相覆盖。
