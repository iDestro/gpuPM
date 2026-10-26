# 用户组与任务策略继承

管理员统一配置；本次不增加普通用户登录入口。用户组只管理任务属性，与共享目录直接授权、系统组及系统权限独立。

## 规则

- 默认组（内置）引用策略配置；新用户进入默认组。
- 普通组逐项继承全局或覆盖：priority、max_runtime_seconds、protected、deadline_action、orphan_reminder、orphan_wait_seconds。
- 每个用户保留 personal_policy，初始为空（全部继承全局）。仅选择内置自定义组时生效。切换到其他组保留但不应用个人配置。
- 自定义组只是分类，无共同策略；两个内置组不可删除或改名。普通组删除时确认将成员移回默认组。
- 有效策略：任务单独设置 > 当前用户分配所解析的配置 > 全局；普通组和个人配置互斥，不能叠加。
- JSON 字段缺失表示继承；max_runtime_seconds:null 明确表示不限时，不能等同于继承。其他字段不能为 null。
- 任务首次同步时固定有效策略及来源；后续修改全局、组、个人配置或分组只影响新任务。已有任务仅由明确的任务编辑修改。
- 维护账号/非人员/未纳管/停用/删除等账号不能通过任务策略编辑绕过现有保护。
- 界面展示有效值、来源；用户详情内编辑分组和个人配置。用户组页展示组策略、成员；移除冗余用户业务策略页面和权限组主导航，旧链接重定向。
- 原有原生系统组编辑作为账号高级功能保留，不创建同名系统组，不更改共享 ACL。
- 中英文、紧凑桌面及移动布局、小时分钟秒输入、错误提示和取消行为全部覆盖。

## 接口约定

/groups 返回 id,name,notes,is_default,is_custom,policy_overrides,effective_policy,policy_sources,member_count。来源为 global/group/personal；自定义组 effective_policy 为空。
POST/PATCH /groups 支持 policy_overrides 对象（整体替换，空对象恢复继承）；兼容旧 priority 输入但统一转换为 override。
/users 返回原字段及 personal_policy,effective_policy,policy_sources,group_name,policy_editable。PATCH /users/{uid} 接受 group_id,personal_policy，未提交 personal_policy 时保留原记录。
GET /accounts/{id} 沿用已有字段；前端从 /users 按 uid 查策略以复用统一入口。
DELETE /groups/{id}?move_to=1：默认迁回默认组，其他迁入目标不作为新界面选项。

## 迁移

升级前备份 API/agent 数据库、服务源代码和前端。幂等添加字段和内置组，保留旧优先级列，普通组旧优先级映射为组覆盖。旧个人优先级保存在个人配置中；非默认个人优先级用户转自定义组并记录原组/旧值的迁移审计；不能精确保留旧三级排序，已有任务保留旧排序快照，新任务使用单一有效优先级。默认组旧名称可记录到迁移审计并改为默认组；内置自定义组按标记辨识避免名称碰撞。
升级时已有任务固定原有效值，不以新的用户组配置覆盖。禁止迁移修改 /etc/passwd、/etc/group、已有目录和 ACL。失败时恢复备份，禁止向旧版本数据库写入无法解释的新配置。

## 验收

继承动态变化、单字段覆盖、显式不限时、个人配置互斥与保存、内置组保护、普通组删除回默认组、重复升级/旧数据/任务快照、账号保护、字段边界验证、审计及请求失败；覆盖组页和账号页中英文实际浏览器操作与窄屏布局；共享目录及原生权限回归。
