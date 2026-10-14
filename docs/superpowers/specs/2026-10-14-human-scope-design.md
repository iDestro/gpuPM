# human 管理边界

用户已确认：human 成员才可管理，其他账号/任务只读。真实成员包含 wuzhaoxiang、luwangxing、dingpeixuan 及本项目创建的 gpupmqa_ 测试账号；gpupm 服务账号保持非 human。保留维护账号原有保护。

human 为普通附属 Linux 组；新建账号自动加入，私人主组不变。不从 UID/shell 推测 human 身份，不自动纳管已有账号。账号、任务列表默认 human，提供 other/all 分类；GPU 总量仍包含全部任务。业务用户优先级、任务策略、归组、终止、账号/配额/共享成员修改均核验 human 身份。成员移出 human 后后台停止账号策略执行和自动终止；执行已排队终止作业在发信号前再核验。human 组本身禁止 Web 删除/改名/成员修改，成员边界仅 root 管理；常规账号修改不得移出 human。

任务列表增加终止按钮，复用已有详情预览流程；other 只读，保护任务仍不可终止。试用真实入口仍保持 root allow_mutations=false，演示入口可体验操作。
