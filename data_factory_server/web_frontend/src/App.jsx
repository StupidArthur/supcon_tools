import React from 'react'
import { BrowserRouter as Router, Routes, Route, useLocation, Navigate } from 'react-router-dom'
import { Layout } from 'antd'
import Header from './components/Layout/Header'
import Home from './pages/Home'
import DataSimulation from './pages/DataSimulation'
import RealtimeDev from './pages/RealtimeDev'
import History from './pages/History'
import RealtimeRun from './pages/RealtimeRun'
import Doc from './pages/Doc'
import ServiceStatus from './pages/ServiceStatus'
import Infrastructure from './pages/Infrastructure'
import './App.css'

const { Content } = Layout

/**
 * 主应用组件
 * 使用 React Router 进行路由管理
 */
function AppContent() {
  const location = useLocation()

  // 根据当前路径确定选中的菜单项
  const getCurrentPage = () => {
    const path = location.pathname
    if (path === '/') return 'home'
    if (path === '/simu') return 'simulation'
    if (path === '/history') return 'history'
    if (path === '/realtime') return 'realtime'
    if (path === '/debug') return 'debug'
    if (path === '/doc') return 'doc'
    if (path === '/service_status') return 'service_status'
    if (path === '/infra') return 'infrastructure'
    return 'home'
  }

  const menuItems = [
    {
      key: 'home',
      path: '/',
      icon: 'HomeOutlined',
      label: '首页',
    },
    {
      key: 'simulation',
      path: '/simu',
      icon: 'DatabaseOutlined',
      label: '数据模拟',
    },
    {
      key: 'history',
      path: '/history',
      icon: 'PlayCircleOutlined',
      label: '历史数据',
    },
    {
      key: 'realtime',
      path: '/realtime',
      icon: 'PlayCircleOutlined',
      label: '实时数据',
    },
    {
      key: 'doc',
      path: '/doc',
      icon: 'FileTextOutlined',
      label: '文档',
    },
    {
      key: 'debug',
      path: '/debug',
      icon: 'PlayCircleOutlined',
      label: '调试',
    },
    {
      key: 'service_status',
      path: '/service_status',
      icon: 'MonitorOutlined',
      label: '服务诊断',
    },
    {
      key: 'infrastructure',
      path: '/infra',
      icon: 'SettingOutlined',
      label: '引擎管理',
    },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        menuItems={menuItems}
        currentPage={getCurrentPage()}
      />
      <Content style={{ padding: '24px', background: '#f0f2f5' }}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/simu" element={<DataSimulation />} />
          <Route path="/history" element={<History />} />
          <Route path="/realtime" element={<RealtimeRun />} />
          <Route path="/debug" element={<RealtimeDev />} />
          <Route path="/doc" element={<Doc />} />
          <Route path="/service_status" element={<ServiceStatus />} />
          <Route path="/infra" element={<Infrastructure />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Content>
    </Layout>
  )
}

function App() {
  return (
    <Router>
      <AppContent />
    </Router>
  )
}

export default App
