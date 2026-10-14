import { appMessages } from './messages-app';
import { componentMessages } from './messages-components';
import { pageMessages } from './messages-pages';
export const messages: Record<string,string> = {...pageMessages,...componentMessages,...appMessages,
  '宿主机模式':'Host mode',
  '不限时':'Unlimited',
  'gpuPM · 服务器管理':'gpuPM · Server management',
};
