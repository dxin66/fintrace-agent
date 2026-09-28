import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { App } from './App';
import './style.css';
const root = document.getElementById('root');
if (!root) throw new Error('Root element missing');
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1c6661',
          borderRadius: 9,
          fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
