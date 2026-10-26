import { groupMessages } from "./messages-groups";
import { storageMessages } from './messages-storage';
import { readinessMessages } from './messages-readiness';
import { appMessages } from './messages-app';
import { componentMessages } from './messages-components';
import { pageMessages } from './messages-pages';
export const messages: Record<string,string> = {...storageMessages,...readinessMessages,...pageMessages,...componentMessages,...appMessages,...groupMessages,
  '显示实际磁盘占用，硬链接不重复计算；已有缓存需手动刷新后更新。':'Shows allocated disk space, counting hard links once. Refresh manually to update previously cached measurements.',
  '返回编辑并核对':'Return to edit and review',
  '正在执行，请等待服务器返回结果。关闭窗口不会取消操作。':'Executing. Wait for the server result; closing a window does not cancel the operation.',
  '已刷新服务器状态并保留草稿，请核对当前成员与拟保存成员后再预览。':'Server state refreshed and draft retained. Review current and proposed members before previewing again.',
  '当前成员':'Current members',
  '目标已不存在，请关闭窗口并刷新列表。':'The target no longer exists. Close the dialog and refresh the list.',
  '已刷新账号状态并保留草稿，请核对后再保存。':'Account state refreshed and draft retained. Review before saving again.',
  '宿主机模式':'Host mode',
  '不限时':'Unlimited',
  'gpuPM · 服务器管理':'gpuPM · Server management',
};
