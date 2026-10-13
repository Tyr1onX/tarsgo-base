# School Leave v1 生产运维

学校请假材料仍由管理员下载后人工通过微信或 QQ 私聊老师发送。系统不自动发送消息或附件。

## 私有配置

生产 .env 配置：

~~~dotenv
LEAVE_CONTACT_PHONE=<private teacher contact phone>
LEAVE_DAILY_CUTOFF=11:30
~~~

LEAVE_CONTACT_PHONE 不进入仓库。未配置时，成员仍可提交和汇总，但管理员下载 DOCX/ZIP 会明确失败，避免生成缺少联系电话的正式材料。

LEAVE_DAILY_CUTOFF 使用 HH:MM 24 小时格式，时区固定为 Asia/Shanghai。

## 定时汇总

Web 请求不承担调度。可重复调用的 job：

~~~bash
docker compose exec -T api python -m app.jobs.collect_school_leave
~~~

生产 VPS 使用 systemd timer：

~~~bash
sudo ./scripts/install_school_leave_timer.sh
~~~

脚本读取当前 .env 的 LEAVE_DAILY_CUTOFF，安装 tarsgo-school-leave.service 和 tarsgo-school-leave.timer，并显示下一次触发时间。修改截止时间后重新运行安装脚本即可更新 timer。

手动汇总和定时 job 都调用同一个数据库汇总 service。没有 pending 申请时 job 安全 no-op。

## 发布顺序

1. 备份 MySQL。
2. 更新代码和镜像。
3. 执行 alembic upgrade head。
4. 启动/更新 API 与 Web。
5. 检查 /api/health。
6. 登录验证“我的”学号维护和“学校请假”页面。
7. 以 admin 验证汇总管理页面。
8. 不创建真实请假数据，只执行一次无 pending 的 job 验证。
9. 安装或刷新 systemd timer，并检查下一次触发时间。

生成的 DOCX/ZIP 通过内存响应生成，不需要持久化到仓库或服务器材料目录。

## 请假条请求留痕与管理员提醒

日常请假条分别记录 `POST` 准备请求和 `GET` 文件请求，每条留痕包含请求时间、`daily-leave-v2` 文件版本和标准版/线下签章版。首次创建事项的准备请求标记为首次生成；已存在事项的后续准备请求标记为重复准备；`GET` 请求按该事项首次或重复文件请求标记。请求留痕在文件生成前提交，因此只说明请求已到达服务端，不代表 DOCX 已成功生成或保存到成员设备。

仅首次创建请假事项时产生管理员更新事件。管理员导航栏的小红点及请假记录中的“新事项”状态按管理员账号分别保存；一位管理员标记已读不会影响其他管理员。迁移只创建请求留痕、更新事件和个人已读回执表，不回填上线前的历史记录，因此既有记录默认按已读处理。
